"""Local, append-only recognition snapshots and a spreadsheet-friendly index."""
import csv
import fcntl
import hashlib
import io
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .profanity import ProfanityMatcher
from .utils import write_json

FIELDS = [
    "run_id", "record_kind", "timestamp_utc", "cache_modified_at_utc", "source",
    "source_sha256", "backend", "device", "model", "audio_index", "duration_seconds",
    "total_words", "explicit_words", "analysis_seconds", "recognition_seconds",
    "cache_hit", "backend_version", "compute_type", "matcher_sha256", "cache_path",
    "snapshot", "words_csv",
]
WORD_FIELDS = ["word", "start", "end", "profane", "speaker", "speaker_coverage"]


def utc_time(seconds=None):
    value = datetime.now(timezone.utc) if seconds is None else datetime.fromtimestamp(seconds, timezone.utc)
    return value.isoformat(timespec="microseconds" if seconds is None else "seconds")


def matcher_identity():
    root = Path(__file__).resolve().parents[1]
    return hashlib.sha256((root / "profanity.txt").read_bytes() +
                          (root / "censor/profanity.py").read_bytes()).hexdigest()


def csv_text(fields, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Keep filenames/transcribed speech from becoming spreadsheet formulas.
        writer.writerow({key: ("'" + value if isinstance(value, str) and
                               value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value)
                         for key, value in row.items()})
    return output.getvalue()


def write_csv(path, fields, rows):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".history-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(csv_text(fields, rows))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record_run(directory, *, metadata, words, cache_path, source=None, duration=None,
               analysis_seconds=None, recognition_seconds=None, cache_hit=None,
               record_kind="analysis", run_id=None, cache_modified_at=None):
    """One row per audio track; repeated inference never overwrites an earlier run.

    JSON snapshots are authoritative. CSV is rebuilt under a process lock so a
    failed/interrupted index write can be recovered on the next invocation.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    snapshots = directory / "runs"
    snapshots.mkdir(exist_ok=True)
    run_id = run_id or str(uuid.uuid4())
    backend = metadata.get("backend", "")
    row = dict(run_id=run_id, record_kind=record_kind,
               timestamp_utc=utc_time() if record_kind == "analysis" else None,
               cache_modified_at_utc=cache_modified_at, source=str(source) if source else None,
               source_sha256=metadata.get("source_sha256"), backend=backend,
               device={"mlx": "GPU (Metal)", "faster-whisper": "CPU",
                       "whisperkit": "Core ML (automatic)"}.get(backend, "unknown"),
               model=metadata.get("model"), audio_index=metadata.get("audio_index"),
               duration_seconds=duration, total_words=len(words),
               explicit_words=sum(bool(word["profane"]) for word in words),
               analysis_seconds=analysis_seconds, recognition_seconds=recognition_seconds,
               cache_hit=cache_hit, backend_version=metadata.get("backend_version"),
               compute_type=metadata.get("compute_type", metadata.get("compute")),
               matcher_sha256=matcher_identity(), cache_path=str(cache_path),
               snapshot=f"runs/{run_id}.json", words_csv=f"runs/{run_id}.csv")
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / row["snapshot"]
        if not path.exists():
            write_json(path, {"summary": row, "metadata": metadata, "words": words})
        records = []
        for snapshot in sorted(snapshots.glob("*.json")):
            data = json.loads(snapshot.read_text())
            records.append(data["summary"])
            word_csv = directory / data["summary"]["words_csv"]
            if not word_csv.exists():
                write_csv(word_csv, WORD_FIELDS, data["words"])
        records.sort(key=lambda item: (item.get("timestamp_utc") or item.get("cache_modified_at_utc") or "", item["run_id"]))
        write_csv(directory / "runs.csv", FIELDS, records)
    return run_id


def import_cache(directory, cache_path, *, source=None, duration=None):
    """Import each distinct cache snapshot once, including differing Lab results.

    Cache mtime is NOT an inference timestamp. Old caches contain neither total
    inference duration nor original media duration, so these remain unknown.
    """
    cache_path = Path(cache_path).resolve()
    content = cache_path.read_bytes()
    data = json.loads(content)
    matcher = ProfanityMatcher.from_file(Path(__file__).resolve().parents[1] / "profanity.txt")
    words = [{**word, "profane": matcher.matches(word["word"])} for word in data["words"]]
    identity = hashlib.sha256(str(cache_path).encode() + b"\0" + content).hexdigest()
    return record_run(directory, metadata=data["metadata"], words=words, cache_path=cache_path,
                      source=source, duration=duration, record_kind="cache_import",
                      run_id="import-" + identity, cache_modified_at=utc_time(cache_path.stat().st_mtime))
