"""Application configuration."""

import os
import logging
from pathlib import Path
from typing import Set

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
API_ID: int = int(os.getenv("API_ID", "0") or 0)
API_HASH: str = os.getenv("API_HASH", "").strip()

# Comma-separated Telegram user IDs who can use the bot
_admin_raw = os.getenv("ADMIN_IDS", os.getenv("OWNER_ID", "0"))
ADMIN_IDS: Set[int] = set()
for part in str(_admin_raw).split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.add(int(part))

BASE_DIR = Path(__file__).resolve().parent
TEMP_BASE = Path(os.getenv("TEMP_DIR", "/tmp/video_bot"))
TEMP_BASE.mkdir(parents=True, exist_ok=True)

LOG_FILE = TEMP_BASE / "bot.log"
LOG_LEVEL = logging.INFO

SUPPORTED_FORMATS = {"mp4", "mkv", "avi", "mov", "webm", "m4v", "flv", "ts", "mpeg", "mpg"}

# Max file size hints (Telegram limits)
MAX_FILE_SIZE_NORMAL = 2 * 1024 * 1024 * 1024   # 2 GB
MAX_FILE_SIZE_PREMIUM = 4 * 1024 * 1024 * 1024  # 4 GB

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Download timeouts
DOWNLOAD_TIMEOUT = 3600          # 1 hour for large files
CONVERT_TIMEOUT = 1800           # 30 min
SPLIT_TIMEOUT = 1800
