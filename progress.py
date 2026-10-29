"""Progress tracking and display."""

import time
import humanize


class ProgressTracker:
    """Tracks byte progress with speed and ETA."""

    def __init__(self, total: int, description: str = "Processing"):
        self.total = max(total, 1)
        self.description = description
        self.start_time = time.monotonic()
        self.last_current = 0

    def update(self, current: int) -> str:
        current = max(0, min(current, self.total))
        self.last_current = current
        elapsed = time.monotonic() - self.start_time

        if elapsed <= 0.1:
            speed = 0.0
            eta = 0
        else:
            speed = current / elapsed
            remaining = self.total - current
            eta = int(remaining / speed) if speed > 0 else 0

        pct = int(current * 100 / self.total) if self.total else 0
        bar_len = 12
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        return (
            f"{self.description}\n"
            f"{bar} {pct}%\n"
            f"{humanize.naturalsize(current)} / {humanize.naturalsize(self.total)}\n"
            f"{humanize.naturalsize(speed)}/s  •  ETA {eta}s"
        )
