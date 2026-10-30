"""Common utilities."""

from pathlib import Path

from telegram import Update

import admins


def is_supported_format(filename: str) -> bool:
    ext = Path(filename).suffix.lstrip(".").lower()
    from config import SUPPORTED_FORMATS
    return ext in SUPPORTED_FORMATS


def safe_filename(name: str, default: str = "video.mp4") -> str:
    if not name:
        return default
    name = Path(name).name
    for ch in '<>:"/\\|?*\0':
        name = name.replace(ch, "_")
    name = name.strip(". ")
    if not name or name in (".", ".."):
        return default
    return name[:200]


def format_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def is_url(text: str) -> bool:
    text = (text or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def user_is_admin(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    return admins.is_admin(user.id)
