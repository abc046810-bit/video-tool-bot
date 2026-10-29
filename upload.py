"""Upload clips using Pyrogram MTProto client."""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from pyrogram import Client

from ffmpeg_utils import get_video_info, generate_thumbnail
from progress import ProgressTracker

logger = logging.getLogger(__name__)


async def _prepare_video_meta(video_path: Path) -> dict:
    """Get duration, size and thumbnail for a video file."""
    info = {"duration": 0, "width": 0, "height": 0, "thumb": None}
    try:
        meta = await get_video_info(video_path)
        info["duration"] = meta.get("duration") or 0
        info["width"] = meta.get("width") or 0
        info["height"] = meta.get("height") or 0
    except Exception as exc:
        logger.warning("Could not read video info for %s: %s", video_path.name, exc)

    thumb_path = video_path.with_suffix(".thumb.jpg")
    try:
        thumb = await generate_thumbnail(video_path, thumb_path)
        if thumb:
            info["thumb"] = str(thumb)
    except Exception as exc:
        logger.warning("Thumbnail failed for %s: %s", video_path.name, exc)

    return info


async def upload_clips(
    client: Client,
    chat_id: int,
    clips: List[Path],
    status_msg,
    caption_prefix: str = "Part",
) -> None:
    """Upload video clips with live progress, correct duration and thumbnail."""
    total = len(clips)

    for idx, clip_path in enumerate(clips, 1):
        if not clip_path.exists():
            logger.warning("Skipping missing clip: %s", clip_path)
            continue

        file_size = clip_path.stat().st_size
        tracker = ProgressTracker(
            file_size,
            f"⬆️ Uploading {caption_prefix} {idx}/{total}…",
        )
        state = {"current": 0}

        def progress(current: int, total_bytes: int):
            state["current"] = current

        caption = f"{caption_prefix} {idx}/{total}"
        meta = await _prepare_video_meta(clip_path)

        kwargs = {
            "chat_id": chat_id,
            "video": str(clip_path),
            "caption": caption,
            "supports_streaming": True,
            "progress": progress,
        }
        if meta["duration"] > 0:
            kwargs["duration"] = meta["duration"]
        if meta["width"] > 0 and meta["height"] > 0:
            kwargs["width"] = meta["width"]
            kwargs["height"] = meta["height"]
        if meta["thumb"]:
            kwargs["thumb"] = meta["thumb"]

        task = asyncio.create_task(client.send_video(**kwargs))

        last_text = ""
        while not task.done():
            await asyncio.sleep(2.5)
            text = tracker.update(state["current"])
            if text != last_text:
                try:
                    await status_msg.edit_text(text)
                    last_text = text
                except Exception:
                    pass

        await task
        logger.info(
            "Uploaded %s (duration=%ss, %sx%s)",
            clip_path.name,
            meta["duration"],
            meta["width"],
            meta["height"],
        )

        # Clean thumbnail
        if meta["thumb"]:
            try:
                Path(meta["thumb"]).unlink(missing_ok=True)
            except Exception:
                pass


async def upload_single_video(
    client: Client,
    chat_id: int,
    video_path: Path,
    status_msg,
    caption: Optional[str] = None,
) -> None:
    """Upload a single video with progress, correct duration and thumbnail."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    file_size = video_path.stat().st_size
    tracker = ProgressTracker(file_size, "⬆️ Uploading video…")
    state = {"current": 0}

    def progress(current: int, total_bytes: int):
        state["current"] = current

    meta = await _prepare_video_meta(video_path)

    kwargs = {
        "chat_id": chat_id,
        "video": str(video_path),
        "caption": caption or video_path.name,
        "supports_streaming": True,
        "progress": progress,
    }
    if meta["duration"] > 0:
        kwargs["duration"] = meta["duration"]
    if meta["width"] > 0 and meta["height"] > 0:
        kwargs["width"] = meta["width"]
        kwargs["height"] = meta["height"]
    if meta["thumb"]:
        kwargs["thumb"] = meta["thumb"]

    task = asyncio.create_task(client.send_video(**kwargs))

    last_text = ""
    while not task.done():
        await asyncio.sleep(2.5)
        text = tracker.update(state["current"])
        if text != last_text:
            try:
                await status_msg.edit_text(text)
                last_text = text
            except Exception:
                pass

    await task
    logger.info(
        "Uploaded single video: %s (duration=%ss)",
        video_path.name,
        meta["duration"],
    )

    if meta["thumb"]:
        try:
            Path(meta["thumb"]).unlink(missing_ok=True)
        except Exception:
            pass
