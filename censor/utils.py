import json
import math
import os
import tempfile
from pathlib import Path


class CensorError(Exception):
    """An actionable error intended for the CLI."""


def finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CensorError(f"{name} must be a number.")
    if not math.isfinite(value):
        raise CensorError(f"{name} must be finite.")
    return float(value)


def timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    minutes, millis = divmod(millis, 60000)
    return f"{minutes:02d}:{millis // 1000:02d}.{millis % 1000:03d}"


def write_json(path: Path, data: dict) -> None:
    """Atomically update only application-owned JSON (caller checks collisions)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
