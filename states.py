"""Conversation states."""

from enum import IntEnum, auto


class BotState(IntEnum):
    # Split – flexible: accept duration and/or video/link in any order
    SPLIT_COLLECT = auto()

    # Merge
    MERGE_COLLECT = auto()

    # Timeline
    TIMELINE_WAIT_VIDEO = auto()
    TIMELINE_WAIT_BUTTON = auto()
    TIMELINE_WAIT_RANGES = auto()

    # Download / Convert
    DOWNLOAD_WAIT_URL = auto()
