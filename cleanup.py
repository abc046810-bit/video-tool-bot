"""Session cleanup utilities."""

import logging
import shutil
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import config

logger = logging.getLogger(__name__)


def user_temp_dir(user_id: int) -> Path:
    return config.TEMP_BASE / str(user_id)


def cleanup_user(user_id: int) -> None:
    """Remove all temporary files for a user."""
    user_dir = user_temp_dir(user_id)
    if user_dir.exists():
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
            logger.info("Cleaned user dir: %s", user_dir)
        except Exception as exc:
            logger.warning("Cleanup failed for %s: %s", user_dir, exc)


def cleanup_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove temp files and clear user_data for the current user."""
    user = update.effective_user
    if user:
        cleanup_user(user.id)

    keys = (
        "split_duration",
        "merge_clips",
        "timeline_video_path",
        "download_url",
    )
    for key in keys:
        context.user_data.pop(key, None)
