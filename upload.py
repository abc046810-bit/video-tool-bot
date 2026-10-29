"""Upload clips using Pyrogram MTProto client."""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from pyrogram import Client

from progress import ProgressTracker

logger = logging.getLogger(__name__)


async def upload_clips(
    client: Client,
    chat_id: int,
    clips: List[Path],
    status_msg,
    caption_prefix: str = "Part",
) -> None:
    """Upload video clips with live progress."""
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

        task = asyncio.create_task(
            client.send_video(
                chat_id=chat_id,
                video=str(clip_path),
                caption=caption,
                supports_streaming=True,
                progress=progress,
            )
        )

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
        logger.info("Uploaded %s", clip_path.name)


async def upload_single_video(
    client: Client,
    chat_id: int,
    video_path: Path,
    status_msg,
    caption: Optional[str] = None,
) -> None:
    """Upload a single video with progress."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    file_size = video_path.stat().st_size
    tracker = ProgressTracker(file_size, "⬆️ Uploading video…")
    state = {"current": 0}

    def progress(current: int, total_bytes: int):
        state["current"] = current

    task = asyncio.create_task(
        client.send_video(
            chat_id=chat_id,
            video=str(video_path),
            caption=caption or video_path.name,
            supports_streaming=True,
            progress=progress,
        )
    )

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
    logger.info("Uploaded single video: %s", video_path.name)
