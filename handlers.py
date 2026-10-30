"""Telegram bot command and conversation handlers – premium UI."""

import logging
import re
from pathlib import Path

from telegram import Update, ReplyKeyboardRemove
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
import admins
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
from upload import upload_clips, upload_single_video, upload_one_clip
from utils import is_supported_format, is_url, safe_filename, user_is_admin
from states import BotState
from keyboards import main_menu_keyboard, cancel_keyboard, timeline_inline

logger = logging.getLogger(__name__)


async def _safe_edit(status_msg, text: str, **kwargs) -> None:
    """Edit status message without raising on 429 / network errors."""
    try:
        await status_msg.edit_text(text, **kwargs)
    except Exception:
        pass



def admin_filter():
    """Dynamic filter – checks current admin list (owners + extra)."""
    class _AdminFilter(filters.MessageFilter):
        def filter(self, message):
            user = message.from_user
            return bool(user and admins.is_admin(user.id))
    return _AdminFilter()


ADMIN = admin_filter()


# ─────────────────────────────────────────────
#  Menu button text → command mapping
# ─────────────────────────────────────────────

MENU_MAP = {
    "✂️ Split": "split",
    "🔗 Merge": "merge",
    "🎞 Timeline": "timeline",
    "⬇️ Download": "download",
    "📖 Help": "help",
    "❌ Cancel": "cancel",
}


# ─────────────────────────────────────────────
#  Basic commands
# ─────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    text = (
        f"👋 Welcome, *{name}*!\n\n"
        "🎬 *Video Tool Bot* — Premium edition\n"
        "Split • Merge • Timeline • Download\n"
        "Large files up to 2–4 GB supported.\n\n"
        "Use the *buttons below* or the / menu.\n"
        "Tap a tool to get started."
    )
    await update.effective_message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Help Guide*\n\n"
        "*✂️ Split*\n"
        "Send duration (e.g. `30`) and a video *or* link — any order.\n"
        "Bot cuts the whole video into equal parts.\n\n"
        "*🔗 Merge*\n"
        "Send clips one by one → then /done.\n\n"
        "*🎞 Timeline*\n"
        "Upload video → enter ranges like `00:07-00:15`.\n\n"
        "*⬇️ Download*\n"
        "Paste a direct video URL → get MP4 back.\n\n"
        "*Admin*\n"
        "`/admins` — list\n"
        "`/addadmin <id>` — add (owner only)\n"
        "`/removeadmin <id>` — remove (owner only)\n\n"
        "Use ❌ Cancel anytime to stop a job."
    )
    await update.effective_message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text(
        "✅ Cancelled. Temp files cleaned.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Access denied.\nOnly admins can use this bot.",
            reply_markup=ReplyKeyboardRemove(),
        )


# ─────────────────────────────────────────────
#  Admin management
# ─────────────────────────────────────────────

async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        admins.list_admins_text(),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not admins.is_owner(user.id):
        await update.effective_message.reply_text("⛔ Only owners can add admins.")
        return ConversationHandler.END

    # Allow /addadmin 123456789 directly
    if context.args:
        try:
            uid = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("❌ Invalid user ID. Use numbers only.")
            return ConversationHandler.END
        if admins.add_admin(uid):
            await update.effective_message.reply_text(
                f"✅ Admin added: `{uid}`",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await update.effective_message.reply_text(
                f"ℹ️ Already admin (or is owner): `{uid}`",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        return ConversationHandler.END

    await update.effective_message.reply_text(
        "➕ Send the Telegram *user ID* to add as admin.\n"
        "(User must have started the bot at least once)\n\n"
        "Or use: `/addadmin 123456789`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.ADD_ADMIN_WAIT_ID


async def addadmin_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    if text in ("❌ Cancel", "/cancel"):
        return await cancel_command(update, context)
    try:
        uid = int(text)
    except ValueError:
        await update.effective_message.reply_text("❌ Send a numeric user ID.")
        return BotState.ADD_ADMIN_WAIT_ID

    if admins.add_admin(uid):
        await update.effective_message.reply_text(
            f"✅ Admin added: `{uid}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            f"ℹ️ Already admin or is owner: `{uid}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    return ConversationHandler.END


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not admins.is_owner(user.id):
        await update.effective_message.reply_text("⛔ Only owners can remove admins.")
        return ConversationHandler.END

    if context.args:
        try:
            uid = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("❌ Invalid user ID.")
            return ConversationHandler.END
        if uid in config.OWNER_IDS:
            await update.effective_message.reply_text("⛔ Cannot remove an owner.")
            return ConversationHandler.END
        if admins.remove_admin(uid):
            await update.effective_message.reply_text(
                f"✅ Admin removed: `{uid}`",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await update.effective_message.reply_text(
                f"ℹ️ Not in extra admins: `{uid}`",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        return ConversationHandler.END

    await update.effective_message.reply_text(
        "➖ Send the Telegram *user ID* to remove.\n"
        "Or use: `/removeadmin 123456789`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.REMOVE_ADMIN_WAIT_ID


async def removeadmin_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    if text in ("❌ Cancel", "/cancel"):
        return await cancel_command(update, context)
    try:
        uid = int(text)
    except ValueError:
        await update.effective_message.reply_text("❌ Send a numeric user ID.")
        return BotState.REMOVE_ADMIN_WAIT_ID

    if uid in config.OWNER_IDS:
        await update.effective_message.reply_text(
            "⛔ Cannot remove an owner.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    if admins.remove_admin(uid):
        await update.effective_message.reply_text(
            f"✅ Admin removed: `{uid}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            f"ℹ️ Not in extra admins: `{uid}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Menu button router
# ─────────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Map reply-keyboard button presses to the right flow."""
    text = (update.effective_message.text or "").strip()
    cmd = MENU_MAP.get(text)
    if not cmd:
        return None
    if cmd == "split":
        return await split_command(update, context)
    if cmd == "merge":
        return await merge_command(update, context)
    if cmd == "timeline":
        return await timeline_command(update, context)
    if cmd == "download":
        return await download_command(update, context)
    if cmd == "help":
        await help_command(update, context)
        return ConversationHandler.END
    if cmd == "cancel":
        return await cancel_command(update, context)
    return None


# ─────────────────────────────────────────────
#  SPLIT
# ─────────────────────────────────────────────

async def split_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    context.user_data["split_duration"] = None
    context.user_data["split_pending_url"] = None
    context.user_data["split_pending_msg"] = None

    await update.effective_message.reply_text(
        "✂️ *Split Video*\n\n"
        "Send *both* (any order):\n"
        "1️⃣ Duration in seconds → e.g. `30`\n"
        "2️⃣ Video file *or* direct download link\n\n"
        "_Example: send 30, then the video — or reverse._",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.SPLIT_COLLECT


async def split_collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip() if message.text else ""

    if text in MENU_MAP or text == "❌ Cancel":
        if text == "❌ Cancel":
            return await cancel_command(update, context)
        result = await menu_router(update, context)
        return result if result is not None else BotState.SPLIT_COLLECT

    duration = context.user_data.get("split_duration")

    if text and not is_url(text):
        try:
            val = int(text)
            if 1 <= val <= 7200:
                context.user_data["split_duration"] = val
                duration = val
                has_media = bool(
                    context.user_data.get("split_pending_url")
                    or context.user_data.get("split_pending_msg")
                )
                await message.reply_text(
                    f"✅ Duration set to *{val}s*."
                    + ("\nProcessing…" if has_media else "\nNow send the *video* or *link*."),
                    parse_mode="Markdown",
                    reply_markup=cancel_keyboard(),
                )
            else:
                await message.reply_text(
                    "❌ Duration must be 1–7200 seconds.\nExample: `30`",
                    parse_mode="Markdown",
                )
                return BotState.SPLIT_COLLECT
        except ValueError:
            if not (message.video or message.document):
                await message.reply_text(
                    "❌ Send a number, a video, or a direct link.",
                    reply_markup=cancel_keyboard(),
                )
                return BotState.SPLIT_COLLECT

    if text and is_url(text):
        context.user_data["split_pending_url"] = text
        context.user_data["split_pending_msg"] = None
        if not duration:
            await message.reply_text(
                "✅ Link received.\nNow send *duration* in seconds (e.g. `30`).",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard(),
            )
            return BotState.SPLIT_COLLECT

    elif message.video or message.document:
        video = message.video or message.document
        file_name = getattr(video, "file_name", None) or f"video_{video.file_id[:12]}.mp4"
        file_name = safe_filename(file_name)
        if not is_supported_format(file_name):
            fmts = ", ".join(sorted(config.SUPPORTED_FORMATS))
            await message.reply_text(f"❌ Unsupported format.\nSupported: {fmts}")
            return BotState.SPLIT_COLLECT
        context.user_data["split_pending_msg"] = message
        context.user_data["split_pending_url"] = None
        if not duration:
            await message.reply_text(
                "✅ Video received.\nNow send *duration* in seconds (e.g. `30`).",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard(),
            )
            return BotState.SPLIT_COLLECT

    duration = context.user_data.get("split_duration")
    pending_url = context.user_data.get("split_pending_url")
    pending_msg = context.user_data.get("split_pending_msg")

    if not duration or (not pending_url and not pending_msg):
        return BotState.SPLIT_COLLECT

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

        await _safe_edit(status_msg, "✂️ Splitting + uploading (one-by-one)…")

        sent = {"n": 0}

        async def on_part(part_path, index, total):
            await upload_one_clip(
                pyro_client,
                message.chat_id,
                part_path,
                status_msg,
                index,
                total,
                caption_prefix="Part",
            )
            sent["n"] = index
            try:
                part_path.unlink(missing_ok=True)
            except Exception:
                pass
            await _safe_edit(
                status_msg,
                f"✅ Part {index}/{total} sent — continuing…",
            )

        await split_video(
            input_path,
            temp_dir,
            float(duration),
            status_msg.edit_text,
            on_part=on_part,
        )
        await _safe_edit(
            status_msg,
            f"✅ Split finished — {sent['n']} part(s) sent.",
        )
    except FFmpegError as exc:
        logger.error("Split FFmpeg error: %s", exc)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exc}`", parse_mode="Markdown")
    except Exception as exp:
        logger.exception("Split unexpected error")
        await status_msg.edit_text(f"❌ Error: {exp}")
    finally:
        cleanup_session(update, context)

    await message.reply_text("Home menu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  MERGE
# ─────────────────────────────────────────────

async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    context.user_data["merge_clips"] = []
    await update.effective_message.reply_text(
        "🔗 *Merge Clips*\n\n"
        "Send video clips *in order*.\n"
        "When finished, send /done or type `done`.",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.MERGE_COLLECT


async def merge_receive_clip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip().lower() if message.text else ""

    if text in ("❌ cancel", "/cancel", "cancel"):
        return await cancel_command(update, context)
    if text in ("done", "/done"):
        return await merge_done(update, context)

    video = message.video or message.document
    if not video:
        await message.reply_text(
            "Send a video clip, or /done when finished.",
            reply_markup=cancel_keyboard(),
        )
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
    except Exception as exp:
        logger.exception("Merge receive error")
        await message.reply_text(f"❌ Failed: {exp}")

    return BotState.MERGE_COLLECT


async def merge_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    clips = context.user_data.get("merge_clips", [])

    if not clips:
        await message.reply_text(
            "No clips received. Merge cancelled.",
            reply_markup=main_menu_keyboard(),
        )
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
            pyro_client, message.chat_id, [output_path], status_msg, caption_prefix="Merged"
        )
        await status_msg.edit_text("✅ Merge finished.")
    except FFmpegError as exp:
        logger.error("Merge FFmpeg error: %s", exp)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exp}`", parse_mode="Markdown")
    except Exception as exp:
        logger.exception("Merge unexpected error")
        await status_msg.edit_text(f"❌ Error: {exp}")
    finally:
        cleanup_session(update, context)

    await message.reply_text("Home menu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  TIMELINE
# ─────────────────────────────────────────────

async def timeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text(
        "🎞 *Timeline Cutter*\n\nUpload a video to cut specific time ranges.",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.TIMELINE_WAIT_VIDEO


async def timeline_video_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip() if message.text else ""
    if text in ("❌ Cancel", "/cancel"):
        return await cancel_command(update, context)

    video = message.video or message.document
    if not video:
        await message.reply_text("Please upload a video file.", reply_markup=cancel_keyboard())
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
        await status_msg.edit_text(
            "✅ Video ready. Press the button to enter time ranges.",
            reply_markup=timeline_inline(),
        )
        return BotState.TIMELINE_WAIT_BUTTON
    except Exception as exp:
        logger.exception("Timeline download error")
        await status_msg.edit_text(f"❌ Download failed: {exp}")
        cleanup_session(update, context)
        await message.reply_text("Home menu:", reply_markup=main_menu_keyboard())
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
            "`7-15`",
            parse_mode="Markdown",
        )
        return BotState.TIMELINE_WAIT_RANGES
    return BotState.TIMELINE_WAIT_BUTTON


async def timeline_ranges_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip()
    if text in ("❌ Cancel", "/cancel"):
        return await cancel_command(update, context)

    path_str = context.user_data.get("timeline_video_path")
    if not path_str:
        await message.reply_text("Session expired. Use Timeline again.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    input_path = Path(path_str)
    if not input_path.exists():
        await message.reply_text("Video missing. Start again.", reply_markup=main_menu_keyboard())
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
        await status_msg.edit_text(f"✅ Done — {len(clips)} clip(s) sent.")
    except ValueError as exp:
        await status_msg.edit_text(f"❌ Invalid ranges:\n{exp}")
        return BotState.TIMELINE_WAIT_RANGES
    except FFmpegError as exp:
        logger.error("Timeline FFmpeg error: %s", exp)
        await status_msg.edit_text(f"❌ FFmpeg error:\n`{exp}`", parse_mode="Markdown")
    except Exception as exp:
        logger.exception("Timeline unexpected error")
        await status_msg.edit_text(f"❌ Error: {exp}")
    finally:
        cleanup_session(update, context)

    await message.reply_text("Home menu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  DOWNLOAD
# ─────────────────────────────────────────────

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cleanup_session(update, context)
    await update.effective_message.reply_text(
        "⬇️ *Download & Convert*\n\n"
        "Send a direct video link (mp4 / mkv / webm …).\n"
        "Bot downloads, converts to MP4 if needed, and uploads back.\n\n"
        "Supports large files (2 GB / ~4 GB premium).",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return BotState.DOWNLOAD_WAIT_URL


async def download_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    text = (message.text or "").strip()

    if text in ("❌ Cancel", "/cancel"):
        return await cancel_command(update, context)

    if not is_url(text):
        await message.reply_text(
            "❌ Send a valid http/https link.\nExample: `https://example.com/video.mp4`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
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
            pyro_client, message.chat_id, output_path, status_msg, caption="✅ Downloaded & ready"
        )
        await status_msg.edit_text("✅ Done — video uploaded.")
    except Exception as exp:
        logger.exception("Download feature error")
        await status_msg.edit_text(f"❌ Error:\n{exp}")
    finally:
        cleanup_session(update, context)

    await message.reply_text("Home menu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Register
# ─────────────────────────────────────────────

def setup_handlers(application: Application) -> None:
    # Entry points also accept menu button text via a shared pattern
    menu_texts = list(MENU_MAP.keys())

    split_conv = ConversationHandler(
        entry_points=[
            CommandHandler("split", split_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^✂️ Split$") & ADMIN, split_command),
        ],
        states={
            BotState.SPLIT_COLLECT: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO | filters.Document.ALL | filters.TEXT)
                    & ~filters.COMMAND
                    & ADMIN,
                    split_collect,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    merge_conv = ConversationHandler(
        entry_points=[
            CommandHandler("merge", merge_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^🔗 Merge$") & ADMIN, merge_command),
        ],
        states={
            BotState.MERGE_COLLECT: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO | filters.TEXT) & ADMIN,
                    merge_receive_clip,
                ),
                CommandHandler("done", merge_done, filters=ADMIN),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    timeline_conv = ConversationHandler(
        entry_points=[
            CommandHandler("timeline", timeline_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^🎞 Timeline$") & ADMIN, timeline_command),
        ],
        states={
            BotState.TIMELINE_WAIT_VIDEO: [
                MessageHandler(
                    (filters.VIDEO | filters.Document.VIDEO | filters.TEXT) & ADMIN,
                    timeline_video_input,
                ),
            ],
            BotState.TIMELINE_WAIT_BUTTON: [
                CallbackQueryHandler(timeline_button_callback, pattern="^timeline_cut$"),
            ],
            BotState.TIMELINE_WAIT_RANGES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN, timeline_ranges_input),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    download_conv = ConversationHandler(
        entry_points=[
            CommandHandler("download", download_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^⬇️ Download$") & ADMIN, download_command),
        ],
        states={
            BotState.DOWNLOAD_WAIT_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN, download_url_input),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    addadmin_conv = ConversationHandler(
        entry_points=[CommandHandler("addadmin", addadmin_command, filters=ADMIN)],
        states={
            BotState.ADD_ADMIN_WAIT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN, addadmin_receive_id),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    removeadmin_conv = ConversationHandler(
        entry_points=[CommandHandler("removeadmin", removeadmin_command, filters=ADMIN)],
        states={
            BotState.REMOVE_ADMIN_WAIT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ADMIN, removeadmin_receive_id),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=ADMIN),
            MessageHandler(filters.Regex(r"^❌ Cancel$") & ADMIN, cancel_command),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start_command, filters=ADMIN))
    application.add_handler(CommandHandler("help", help_command, filters=ADMIN))
    application.add_handler(MessageHandler(filters.Regex(r"^📖 Help$") & ADMIN, help_command))
    application.add_handler(CommandHandler("cancel", cancel_command, filters=ADMIN))
    application.add_handler(CommandHandler("admins", admins_command, filters=ADMIN))

    application.add_handler(split_conv)
    application.add_handler(merge_conv)
    application.add_handler(timeline_conv)
    application.add_handler(download_conv)
    application.add_handler(addadmin_conv)
    application.add_handler(removeadmin_conv)

    # Non-admins
    application.add_handler(MessageHandler(~ADMIN, unauthorized))
