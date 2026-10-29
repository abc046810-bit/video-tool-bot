"""Download media from Telegram or external URLs."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import aiohttp
from pyrogram import Client
from telegram import Message

import config
from progress import ProgressTracker
from utils import safe_filename

logger = logging.getLogger(__name__)


async def download_telegram_media(
    client: Client,
    message: Message,
    dest_path: Path,
    status_msg,
) -> Path:
    """Download video/document via Pyrogram MTProto (supports large files)."""
    video = message.video or message.document
    if not video:
        raise ValueError("Message contains no downloadable media")

    file_id = video.file_id
    file_size = getattr(video, "file_size", 0) or 0

    logger.info("TG download started: %s (%s bytes)", str(file_id)[:24], file_size)

    tracker = ProgressTracker(file_size or 1, "⬇️ Downloading from Telegram…")
    state = {"current": 0}

    def progress(current: int, total: int):
        state["current"] = current
        if total and total > 0:
            tracker.total = total

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    task = asyncio.create_task(
        client.download_media(
            file_id,
            file_name=str(dest_path),
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

    result = await task
    if not result:
        raise RuntimeError("Telegram download failed (empty result)")

    final = Path(result)
    if not final.exists() or final.stat().st_size < 100:
        raise RuntimeError("Downloaded file is missing or empty")

    logger.info("TG download finished: %s (%s bytes)", final, final.stat().st_size)
    return final


async def download_url(
    url: str,
    dest_dir: Path,
    status_msg,
    preferred_name: Optional[str] = None,
) -> Path:
    """
    Download a direct video URL (or common hosts) to disk.
    Uses aiohttp streaming to keep memory low (Render-friendly).
    Falls back to yt-dlp style simple extraction for some hosts if needed.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = url.strip()

    # Try yt-dlp first for better host support (YouTube, etc. optional)
    try:
        path = await _download_with_ytdlp(url, dest_dir, status_msg)
        if path and path.exists():
            return path
    except Exception as exc:
        logger.info("yt-dlp path failed or not applicable: %s", exc)

    # Direct HTTP download
    return await _download_direct(url, dest_dir, status_msg, preferred_name)


async def _download_direct(
    url: str,
    dest_dir: Path,
    status_msg,
    preferred_name: Optional[str] = None,
) -> Path:
    timeout = aiohttp.ClientTimeout(total=config.DOWNLOAD_TIMEOUT, sock_connect=30)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Download failed: HTTP {resp.status}")

            # Determine filename
            name = preferred_name
            if not name:
                cd = resp.headers.get("Content-Disposition", "")
                m = re.search(r'filename[*]?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
                if m:
                    name = m.group(1).strip()
            if not name:
                name = url.split("?")[0].rstrip("/").split("/")[-1] or "video.mp4"
            name = safe_filename(name, "video.mp4")

            # Ensure extension
            if not Path(name).suffix:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "webm" in ctype:
                    name += ".webm"
                elif "mkv" in ctype or "matroska" in ctype:
                    name += ".mkv"
                else:
                    name += ".mp4"

            dest_path = dest_dir / name
            total = int(resp.headers.get("Content-Length") or 0)
            tracker = ProgressTracker(total or 1, "⬇️ Downloading…")

            downloaded = 0
            last_text = ""
            chunk_size = 1024 * 256  # 256 KB

            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        tracker.total = total
                    text = tracker.update(downloaded)
                    if text != last_text:
                        try:
                            await status_msg.edit_text(text)
                            last_text = text
                        except Exception:
                            pass

    if not dest_path.exists() or dest_path.stat().st_size < 100:
        raise RuntimeError("Downloaded file is empty or missing")

    logger.info("Direct download finished: %s (%s bytes)", dest_path, dest_path.stat().st_size)
    return dest_path


async def _download_with_ytdlp(url: str, dest_dir: Path, status_msg) -> Optional[Path]:
    """Optional yt-dlp download for non-direct links. Returns None if not useful."""
    try:
        import yt_dlp
    except ImportError:
        return None

    # Only use yt-dlp for known non-direct patterns or when user wants broad support
    # For pure direct .mp4 links, direct download is faster and lighter.
    lower = url.lower()
    direct_exts = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts")
    if any(lower.split("?")[0].endswith(ext) for ext in direct_exts):
        return None

    await status_msg.edit_text("⬇️ Preparing download (yt-dlp)…")

    outtmpl = str(dest_dir / "%(title).180s.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "http_chunk_size": 10485760,
    }

    def _run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    loop = asyncio.get_event_loop()
    filename = await loop.run_in_executor(None, _run)
    path = Path(filename)
    if not path.exists():
        # try common variants
        for p in dest_dir.glob("*"):
            if p.is_file() and p.stat().st_size > 1000:
                return p
        return None
    return path
