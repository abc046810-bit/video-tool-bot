"""Conversation states."""

from enum import IntEnum, auto


class BotState(IntEnum):
    # Split
    SPLIT_ENTER_DURATION = auto()
    SPLIT_WAIT_INPUT = auto()

    # Merge
    MERGE_COLLECT = auto()

    # Timeline
    TIMELINE_WAIT_VIDEO = auto()
    TIMELINE_WAIT_BUTTON = auto()
    TIMELINE_WAIT_RANGES = auto()

    # Download / Convert
    DOWNLOAD_WAIT_URL = auto()
