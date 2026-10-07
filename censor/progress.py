"""Dependency-free progress display for terminals and redirected output."""
import math
import sys
import time
from shutil import get_terminal_size


def clock_text(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"


class Progress:
    def __init__(self, label: str, total: float, unit: str = "seconds", stream=None):
        self.label = label
        self.total = max(float(total), 1e-9)
        self.unit = unit
        self.stream = stream if stream is not None else sys.stdout
        self.tty = self.stream.isatty()
        self.current = 0.0
        self.started = time.monotonic()
        self.last_draw = 0.0
        self.last_percent = -1
        self.width = 0

    def __enter__(self):
        self.started = time.monotonic()
        self._draw(0)
        return self

    def update(self, value: float) -> None:
        if not math.isfinite(value):
            return
        self.current = min(self.total, max(self.current, value, 0))
        percent = min(99, int(self.current / self.total * 100))
        now = time.monotonic()
        if self.tty:
            if now - self.last_draw < .15:
                return
        elif percent // 5 == self.last_percent // 5:
            return
        self._draw(percent)

    def _draw(self, percent: int, final: bool = False, failed: bool = False):
        elapsed = max(0, time.monotonic() - self.started)
        if self.unit == "seconds":
            position = f"{clock_text(self.current)}/{clock_text(self.total)}"
        elif self.unit == "bytes":
            position = f"{self.current / 1048576:.1f}/{self.total / 1048576:.1f} MiB"
        else:
            position = f"{int(self.current)}/{int(self.total)}"
        eta = "--:--"
        if self.current > 0 and elapsed >= 1:
            eta = "~" + clock_text(elapsed * (self.total - self.current) / self.current)
        if final and not failed:
            eta = "00:00"
        suffix = " | stopped" if failed else ""
        details = f" | {position} | elapsed {clock_text(elapsed)} | ETA {eta}{suffix}"
        columns = get_terminal_size().columns if self.tty else 200
        if columns < len(self.label) + len(details) + 13:
            details = f" | {position} | ETA {eta}{suffix}"
        size = max(4, min(20, columns - len(self.label) - len(details) - 10))
        filled = percent * size // 100
        bar = "#" * filled + "-" * (size - filled)
        line = f"{self.label} [{bar}] {percent:3d}%{details}"
        if self.tty:
            # Leave the last column unused to avoid terminal auto-wrap.
            line = line[:max(1, columns - 1)]
            self.stream.write("\r" + line.ljust(min(self.width, columns - 1)) + ("\n" if final else ""))
            self.width = len(line)
        else:
            self.stream.write(line + "\n")
        self.stream.flush()
        self.last_percent = percent
        self.last_draw = time.monotonic()

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.current = self.total
            self._draw(100, final=True)
        else:
            self._draw(min(99, int(self.current / self.total * 100)), final=True, failed=True)
        return False
