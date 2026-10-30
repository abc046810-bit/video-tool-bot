"""Conversation states."""

from enum import IntEnum, auto


class BotState(IntEnum):
    SPLIT_COLLECT = auto()
    MERGE_COLLECT = auto()
    TIMELINE_WAIT_VIDEO = auto()
    TIMELINE_WAIT_BUTTON = auto()
    TIMELINE_WAIT_RANGES = auto()
    DOWNLOAD_WAIT_URL = auto()
    ADD_ADMIN_WAIT_ID = auto()
    REMOVE_ADMIN_WAIT_ID = auto()
