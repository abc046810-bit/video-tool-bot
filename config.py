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

# Bootstrap owners – set once in Render env. These can never be removed via bot.
# Supports ADMIN_IDS or OWNER_ID (comma-separated).
_raw = os.getenv("ADMIN_IDS", "") or os.getenv("OWNER_ID", "0")
OWNER_IDS: Set[int] = set()
for part in str(_raw).split(","):
    part = part.strip()
    if part.isdigit():
        OWNER_IDS.add(int(part))

BASE_DIR = Path(__file__).resolve().parent
TEMP_BASE = Path(os.getenv("TEMP_DIR", "/tmp/video_bot"))
TEMP_BASE.mkdir(parents=True, exist_ok=True)

# Extra admins file (survives until container restart / redeploy – no DB needed)
ADMINS_FILE = TEMP_BASE / "admins.json"

LOG_FILE = TEMP_BASE / "bot.log"
LOG_LEVEL = logging.INFO

SUPPORTED_FORMATS = {"mp4", "mkv", "avi", "mov", "webm", "m4v", "flv", "ts", "mpeg", "mpg"}

MAX_FILE_SIZE_NORMAL = 2 * 1024 * 1024 * 1024
MAX_FILE_SIZE_PREMIUM = 4 * 1024 * 1024 * 1024

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

DOWNLOAD_TIMEOUT = 3600
CONVERT_TIMEOUT = 1800
SPLIT_TIMEOUT = 1800
