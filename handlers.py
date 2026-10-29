"""Telegram bot command and conversation handlers."""

import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from cleanup import cleanup_session, user_temp_dir
from download import download_telegram_media, download_url
from ffmpeg_utils import (
    FFmpegError,
    merge_videos,
    split_video,
    get_duration,
    parse_time_ranges,
    cut_timeline_clips,
    convert_to_mp4,
)
from upload import upload_clips, upload_single_video
from utils import is_admin, is_supported_format, is_url, safe_filename
from states import BotState

logger = logging.getLogger(__name__)

ADMIN_FILTER = filters.User(user_id=list(config.ADMIN_IDS)) if config.ADMIN_IDS else filters.User(user_id=[0])


# ─────────────────────────────────────────────
#  Basic commands
# ─────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🎬 *Video Tool Bot*\n\n"
        "Professional video splitter, merger & downloader.\n"
        "Supports large files (up to 2–4 GB).\n\n"
        "*Commands*\n"
        "• /split – Split video into fixed-duration parts\n"
        "• /merge – Merge multiple clips in order\n"
        "• /timeline – Cut specific time ranges\n"
        "• /download – Download any video link → MP4\n"
        "• /cancel – Cancel current operation\n"
        "• /help – Detailed help\n\n"
        "_Send a video or a direct link after choosing a command._"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Help*\n\n"
        "* /split*\n"
        "Send duration *and* video/link in any order:\n"
        "• Number of seconds (e.g. `30`)\n"
        "• Video upload / forward\n"
        "• Or a direct download link\n"
        "Bot will split the whole video into parts of that length.\n\n"
        "* /merge*\n"
        "1. Send clips one by one (order is preserved)\n"
        "2. Send /done when finished\n\n"
        "* /timeline*\n"
        "1. Upload a video\n"
        "2. Press the button\n"
        "3. Send ranges like:\n"
        "`00:07-00:15`\n"
        "`00:25-00:40, 01:10-01:30`\n\n"
        "* /download*\n"
        "1. Send any direct video link (mp4/mkv/webm…)\n"
        "2. Bot downloads, converts to MP4 if needed, and uploads back\n\n"
        "*Tips*\n"
        "• Large files are supported via MTProto\n"
        "• Use /cancel anytime to stop and clean temp files\n"
        "• Only admins can use this bot"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text("✅ Cancelled. Temporary files cleaned.")
    return ConversationHandler.END


async def unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Access denied. You are not an admin.")


# ─────────────────────────────────────────────
#  SPLIT flow (flexible – duration OR video/link in any order)
# ─────────────────────────────────────────────

async def split_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    context.user_data["split_duration"] = None
    context.user_data["split_pending_url"] = None
    context.user_data["split_pending_msg"] = None

    await update.effective_message.reply_text(
        "⏱ *Split Video*\n\n"
        "Send *both* of these (any order):\n"
        "1️⃣ Duration in seconds → e.g. `30`\n"
        "2️⃣ Video file *or* direct download link\n\n"
        "Example:\n"
        "• First send `30`, then send the video/link\n"
        "• Or first send the video/link, then send `30`",
        parse_mode="Markdown",
    )
    return BotState.SPLIT_COLLECT


async def split_collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept duration (number) or video/link in any order, then process."""
    message = update.effective_message
    text = (message.text or "").strip() if message.text else ""

    duration = context.user_data.get("split_duration")
    has_media = False

    # ── 1) Try to parse as duration ──────────────────────────
    if text and not is_url(text):
        try:
            val = int(text)
            if 1 <= val <= 7200:
                context.user_data["split_duration"] = val
                duration = val
                await message.reply_text(
                    f"✅ Duration set to *{val}s*.\n"
                    + ("Now send the *video* or *direct link*." if not context.user_data.get("split_pending_url")
                       and not context.user_data.get("split_pending_msg")
                       else "Processing…"),
                    parse_mode="Markdown",
                )
            else:
                await message.reply_text(
                    "❌ Duration must be between 1 and 7200 seconds.\nExample: `30`",
                    parse_mode="Markdown",
                )
                return BotState.SPLIT_COLLECT
        except ValueError:
            # Not a number and not a URL → ignore / ask again
            if not (message.video or message.document):
                await message.reply_text(
                    "❌ Send either:\n"
                    "• a number (seconds), e.g. `30`\n"
                    "• a video file\n"
                    "• or a direct http/https link",
                    parse_mode="Markdown",
                )
                return BotState.SPLIT_COLLECT

    # ── 2) URL ───────────────────────────────────────────────
    if text and is_url(text):
        context.user_data["split_pending_url"] = text
        context.user_data["split_pending_msg"] = None
        has_media = True
        if not duration:
            await message.reply_text(
                "✅ Link received.\nNow send the *duration* in seconds (e.g. `30`).",
                parse_mode="Markdown",
            )
            return BotState.SPLIT_COLLECT

    # ── 3) Video / Document ──────────────────────────────────
    elif message.video or message.document:
        video = message.video or message.document
        file_name = getattr(video, "file_name", None) or f"video_{video.file_id[:12]}.mp4"
        file_name = safe_filename(file_name)
        if not is_supported_format(file_name):
            fmts = ", ".join(sorted(config.SUPPORTED_FORMATS))
            await message.reply_text(f"❌ Unsupported format.\nSupported: {fmts}")
            return BotState.SPLIT_COLLECT

        # Store the message so we can download later (file_id stays valid)
        context.user_data["split_pending_msg"] = message
        context.user_data["split_pending_url"] = None
        has_media = True
        if not duration:
            await message.reply_text(
                "✅ Video received.\nNow send the *duration* in seconds (e.g. `30`).",
                parse_mode="Markdown",
            )
            return BotState.SPLIT_COLLECT

    # ── 4) Both ready → process ──────────────────────────────
    duration = context.user_data.get("split_duration")
    pending_url = context.user_data.get("split_pending_url")
    pending_msg = context.user_data.get("split_pending_msg")

    if not duration or (not pending_url and not pending_msg):
        return BotState.SPLIT_COLLECT

    # Run the actual split job
    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id) / "split"
    temp_dir.mkdir(parents=True, exist_ok=True)
    status_msg = await message.reply_text("⏳ Starting…")
    pyro_client = context.bot_data["pyro_client"]

    try:
        if pending_url:
            input_path = await download_url(pending_url, temp_dir, status_msg)
        else:
            video = pending_msg.video or pending_msg.document
            file_name = getattr(video, "file_name", None) or f"video_{video.file_id[:12]}.mp4"
            file_name = safe_filename(file_name)
            input_path = temp_dir / file_name
            await download_telegram_media(pyro_client, pending_msg, input_path, status_msg)

        if input_path.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
            mp4_path = temp_dir / "converted_input.mp4"
            await convert_to_mp4(input_path, mp4_path, status_msg.edit_text)
            input_path = mp4_path

        await status_msg.edit_text("✂️ Splitting video…")
        clips = await split_video(input_path, temp_dir, float(duration), status_msg.edit_text)
        await upload_clips(pyro_client, message.chat_id, clips, status_msg)
        await status_msg.edit_text(f"✅ Split finished – {len(clips)} part(s) sent.")
    except FFmpegError as exc:
        logger.error("Split FFmpeg error: %s", exp := exc)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exc}`", parse_mode="Markdown")
    except Exception as exc:
        logger.exception("Split unexpected error")
        await status_msg.edit_text(f"❌ Error: {exc}")
    finally:
        cleanup_session(update, context)

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  MERGE flow
# ─────────────────────────────────────────────

async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    context.user_data["merge_clips"] = []
    await update.effective_message.reply_text(
        "🔗 *Merge Clips*\n\n"
        "Send the video clips *in the order* you want them merged.\n"
        "When finished, send /done",
        parse_mode="Markdown",
    )
    return BotState.MERGE_COLLECT


async def merge_receive_clip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    video = message.video or message.document

    if not video:
        await message.reply_text("Please upload a video clip.")
        return BotState.MERGE_COLLECT

    file_name = getattr(video, "file_name", None) or f"clip_{video.file_id[:12]}.mp4"
    file_name = safe_filename(file_name)
    if not is_supported_format(file_name):
        fmts = ", ".join(sorted(config.SUPPORTED_FORMATS))
        await message.reply_text(f"❌ Unsupported format. Supported: {fmts}")
        return BotState.MERGE_COLLECT

    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id) / "merge"
    temp_dir.mkdir(parents=True, exist_ok=True)

    clips = context.user_data.setdefault("merge_clips", [])
    count = len(clips) + 1
    ext = Path(file_name).suffix or ".mp4"
    clip_path = temp_dir / f"{count:04d}{ext}"

    try:
        pyro_client = context.bot_data["pyro_client"]
        status_msg = await message.reply_text(f"⬇️ Downloading clip {count}…")
        await download_telegram_media(pyro_client, message, clip_path, status_msg)
        clips.append(clip_path)
        await status_msg.edit_text(f"✅ Clip {count} received. Send next or /done")
    except Exception as exc:
        logger.exception("Merge receive error")
        await message.reply_text(f"❌ Failed to download clip: {exc}")

    return BotState.MERGE_COLLECT


async def merge_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    clips = context.user_data.get("merge_clips", [])

    if not clips:
        await message.reply_text("No clips received. Merge cancelled.")
        cleanup_session(update, context)
        return ConversationHandler.END

    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id)
    output_path = temp_dir / "merged_output.mp4"
    status_msg = await message.reply_text("⏳ Starting merge…")
    pyro_client = context.bot_data["pyro_client"]

    try:
        await merge_videos(clips, output_path, status_msg.edit_text)
        await upload_clips(
            pyro_client,
            message.chat_id,
            [output_path],
            status_msg,
            caption_prefix="Merged",
        )
        await status_msg.edit_text("✅ Merge finished.")
    except FFmpegError as exc:
        logger.error("Merge FFmpeg error: %s", exc)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exc}`", parse_mode="Markdown")
    except Exception as exc:
        logger.exception("Merge unexpected error")
        await status_msg.edit_text(f"❌ Error: {exc}")
    finally:
        cleanup_session(update, context)

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  TIMELINE flow
# ─────────────────────────────────────────────

async def timeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text(
        "✂️ *Timeline Cutter*\n\nUpload a video to cut specific time ranges.",
        parse_mode="Markdown",
    )
    return BotState.TIMELINE_WAIT_VIDEO


async def timeline_video_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    video = message.video or message.document

    if not video:
        await message.reply_text("Please upload a video file.")
        return BotState.TIMELINE_WAIT_VIDEO

    file_name = getattr(video, "file_name", None) or f"video_{video.file_id[:12]}.mp4"
    file_name = safe_filename(file_name)
    if not is_supported_format(file_name):
        fmts = ", ".join(sorted(config.SUPPORTED_FORMATS))
        await message.reply_text(f"❌ Unsupported format. Supported: {fmts}")
        return BotState.TIMELINE_WAIT_VIDEO

    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id) / "timeline"
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_path = temp_dir / file_name

    status_msg = await message.reply_text("⬇️ Downloading video…")
    pyro_client = context.bot_data["pyro_client"]

    try:
        await download_telegram_media(pyro_client, message, input_path, status_msg)
        context.user_data["timeline_video_path"] = str(input_path)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✂️ Cut Timeline Ranges", callback_data="timeline_cut")]
        ])
        await status_msg.edit_text(
            "✅ Video ready. Press the button to enter time ranges.",
            reply_markup=keyboard,
        )
        return BotState.TIMELINE_WAIT_BUTTON
    except Exception as exc:
        logger.exception("Timeline download error")
        await status_msg.edit_text(f"❌ Download failed: {exc}")
        cleanup_session(update, context)
        return ConversationHandler.END


async def timeline_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "timeline_cut":
        await query.edit_message_text(
            "⏱ Send time ranges (one per line or comma-separated):\n\n"
            "Examples:\n"
            "`00:07-00:15`\n"
            "`00:25-00:40, 01:10-01:30`\n"
            "`7-15`\n"
            "`70-90`",
            parse_mode="Markdown",
        )
        return BotState.TIMELINE_WAIT_RANGES
    return BotState.TIMELINE_WAIT_BUTTON


async def timeline_ranges_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip()
    path_str = context.user_data.get("timeline_video_path")
    if not path_str:
        await message.reply_text("Session expired. Use /timeline again.")
        return ConversationHandler.END

    input_path = Path(path_str)
    if not input_path.exists():
        await message.reply_text("Video file missing. Use /timeline again.")
        cleanup_session(update, context)
        return ConversationHandler.END

    status_msg = await message.reply_text("⏳ Processing ranges…")
    pyro_client = context.bot_data["pyro_client"]
    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id) / "timeline"

    try:
        total_dur = await get_duration(input_path)
        ranges = parse_time_ranges(text, total_dur)
        clips = await cut_timeline_clips(input_path, temp_dir, ranges, status_msg.edit_text)
        await upload_clips(pyro_client, message.chat_id, clips, status_msg, caption_prefix="Clip")
        await status_msg.edit_text(f"✅ Done – {len(clips)} clip(s) sent.")
    except ValueError as exc:
        await status_msg.edit_text(f"❌ Invalid ranges:\n{exc}")
        return BotState.TIMELINE_WAIT_RANGES
    except FFmpegError as exc:
        logger.error("Timeline FFmpeg error: %s", exp := exc)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exc}`", parse_mode="Markdown")
    except Exception as exc:
        logger.exception("Timeline unexpected error")
        await status_msg.edit_text(f"❌ Error: {exc}")
    finally:
        cleanup_session(update, context)

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  DOWNLOAD / CONVERT flow
# ─────────────────────────────────────────────

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text(
        "⬇️ *Download & Convert*\n\n"
        "Send a direct video download link (mp4 / mkv / webm / etc.).\n"
        "Bot will download it, convert to MP4 if needed, and send it back.\n\n"
        "Supports large files (2 GB normal, up to ~4 GB with premium).",
        parse_mode="Markdown",
    )
    return BotState.DOWNLOAD_WAIT_URL


async def download_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip()

    if not is_url(text):
        await message.reply_text(
            "❌ Please send a valid http/https link.\n"
            "Example: `https://example.com/video.mp4`",
            parse_mode="Markdown",
        )
        return BotState.DOWNLOAD_WAIT_URL

    user_id = update.effective_user.id
    temp_dir = user_temp_dir(user_id) / "download"
    temp_dir.mkdir(parents=True, exist_ok=True)
    status_msg = await message.reply_text("⏳ Starting download…")
    pyro_client = context.bot_data["pyro_client"]

    try:
        input_path = await download_url(text, temp_dir, status_msg)
        output_path = temp_dir / "output.mp4"
        if input_path.suffix.lower() != ".mp4":
            await convert_to_mp4(input_path, output_path, status_msg.edit_text)
        else:
            try:
                await convert_to_mp4(input_path, output_path, status_msg.edit_text)
            except Exception:
                output_path = input_path

        await upload_single_video(
            pyro_client,
            message.chat_id,
            output_path,
            status_msg,
            caption="✅ Downloaded & ready",
        )
        await status_msg.edit_text("✅ Done – video uploaded.")
    except Exception as exp:
        logger.exception("Download feature error")
        await status_msg.edit_text(f"❌ Error:\n{exp}")
    finally:
        cleanup_session(update, context)

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Register handlers
# ─────────────────────────────────────────────

def setup_handlers(application: Application) -> None:
    split_conv = ConversationHandler(
        entry_points=[CommandHandler("split", split_command, filters=ADMIN_FILTER)],
        states={
            BotState.SPLIT_COLLECT: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO | filters.Document.ALL | filters.TEXT)
                    & ~filters.COMMAND
                    & ADMIN_FILTER,
                    split_collect,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command, filters=ADMIN_FILTER)],
        allow_reentry=True,
    )

    merge_conv = ConversationHandler(
        entry_points=[CommandHandler("merge", merge_command, filters=ADMIN_FILTER)],
        states={
            BotState.MERGE_COLLECT: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO) & ADMIN_FILTER,
                    merge_receive_clip,
                ),
                CommandHandler("done", merge_done, filters=ADMIN_FILTER),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command, filters=ADMIN_FILTER)],
        allow_reentry=True,
    )

    timeline_conv = ConversationHandler(
        entry_points=[CommandHandler("timeline", timeline_command, filters=ADMIN_FILTER)],
        states={
            BotState.TIMELINE_WAIT_VIDEO: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO) & ADMIN_FILTER,
                    timeline_video_input,
                ),
            ],
            BotState.TIMELINE_WAIT_BUTTON: [
                CallbackQueryHandler(timeline_button_callback, pattern="^timeline_cut$"),
            ],
            BotState.TIMELINE_WAIT_RANGES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN_FILTER, timeline_ranges_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command, filters=ADMIN_FILTER)],
        allow_reentry=True,
    )

    download_conv = ConversationHandler(
        entry_points=[CommandHandler("download", download_command, filters=ADMIN_FILTER)],
        states={
            BotState.DOWNLOAD_WAIT_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN_FILTER, download_url_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command, filters=ADMIN_FILTER)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start_command, filters=ADMIN_FILTER))
    application.add_handler(CommandHandler("help", help_command, filters=ADMIN_FILTER))
    application.add_handler(CommandHandler("cancel", cancel_command, filters=ADMIN_FILTER))
    application.add_handler(split_conv)
    application.add_handler(merge_conv)
    application.add_handler(timeline_conv)
    application.add_handler(download_conv)
    application.add_handler(MessageHandler(~ADMIN_FILTER, unauthorized))
