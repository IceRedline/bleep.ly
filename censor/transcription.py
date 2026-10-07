import hashlib
import importlib.metadata
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable, Protocol

from .models import WordTimestamp
from .profanity import ProfanityMatcher
from .utils import CensorError, finite_number, write_json

LOG = logging.getLogger(__name__)
CACHE_VERSION = 1


class TranscriptionBackend(Protocol):
    def transcribe(self, audio: Path, progress: Callable[[float], None]) -> list[WordTimestamp]: ...


class FasterWhisperBackend:
    def __init__(self, model: str, language: str, compute_type: str = "int8", offline: bool = False):
        self.model = model
        self.language = language
        self.compute_type = compute_type
        self.offline = offline

    def transcribe(self, audio: Path, progress: Callable[[float], None]) -> list[WordTimestamp]:
        try:
            import onnxruntime
            # The VAD runtime must not emit telemetry from this local workflow.
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CensorError("faster-whisper is not installed. Run: pip install -r requirements.txt") from exc
        try:
            model = WhisperModel(self.model, device="cpu", compute_type=self.compute_type,
                                 local_files_only=self.offline)
            segments, _ = model.transcribe(str(audio), language=self.language,
                                           word_timestamps=True, vad_filter=True, beam_size=5)
            words = []
            for segment in segments:
                for word in segment.words or []:
                    words.append(WordTimestamp(word.word.strip(), float(word.start), float(word.end)))
                progress(segment.end)
            return words
        except Exception as exc:
            raise CensorError(f"Whisper transcription failed: {exc}. "
                              "Check the local model, free memory and --compute-type float32. "
                              "The first model download requires network access; --offline forbids it.") from exc


def file_hash(path: Path, progress: Callable[[float], None] | None = None) -> str:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
            count += len(block)
            if progress is not None:
                progress(count)
    return digest.hexdigest()


def cache_key(path: Path, model: str, language: str, compute_type: str, audio_index: int,
              progress: Callable[[float], None] | None = None,
              backend: str = "faster-whisper") -> tuple[str, dict]:
    try:
        version = importlib.metadata.version("mlx-whisper" if backend == "mlx" else "faster-whisper")
    except importlib.metadata.PackageNotFoundError:
        version = "uninstalled"
    model_path = Path(model)
    # Local model replacement must invalidate the cache too.
    model_files = ({str(p.relative_to(model_path)): [p.stat().st_size, p.stat().st_mtime_ns]
                    for p in sorted(model_path.rglob("*")) if p.is_file()}
                   if model_path.is_dir() else None)
    metadata = dict(schema=CACHE_VERSION, source_sha256=file_hash(path, progress), backend=backend,
                    backend_version=version, model=model, local_model_files=model_files,
                    language=language, compute_type=compute_type, audio_index=audio_index,
                    word_timestamps=True, vad_filter=True, beam_size=5)
    if backend == "mlx":
        from .mlx_backend import INITIAL_PROMPT
        metadata.update(beam_size=1)
        metadata["initial_prompt"] = INITIAL_PROMPT if language == "ru" else None
        metadata["vad_backend_version"] = importlib.metadata.version("faster-whisper")
        try:
            metadata["mlx_version"] = importlib.metadata.version("mlx")
        except importlib.metadata.PackageNotFoundError:
            metadata["mlx_version"] = "uninstalled"
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return digest, metadata


def parse_words(data: dict, duration: float, require_flags: bool = True) -> list[WordTimestamp]:
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        raise CensorError("Transcript must be an object containing a 'words' array.")
    result = []
    for i, item in enumerate(data["words"]):
        if not isinstance(item, dict) or not isinstance(item.get("word"), str) or not item["word"].strip():
            raise CensorError(f"Transcript word {i}: expected nonempty 'word'.")
        start = finite_number(item.get("start"), f"word {i} start")
        end = finite_number(item.get("end"), f"word {i} end")
        if start < 0 or end <= start or end > duration + .1:
            raise CensorError(f"Transcript word {i}: require 0 <= start < end <= video duration ({duration:.3f}s).")
        if (require_flags or "profane" in item) and not isinstance(item.get("profane"), bool):
            raise CensorError(f"Transcript word {i}: 'profane' must be true or false.")
        result.append(WordTimestamp(item["word"], start, min(end, duration), item.get("profane", False)))
    return sorted(result, key=lambda w: (w.start, w.end))


def read_transcript(path: Path, duration: float, require_flags: bool = True) -> list[WordTimestamp]:
    try:
        return parse_words(json.loads(path.read_text(encoding="utf-8")), duration, require_flags)
    except (OSError, ValueError) as exc:
        raise CensorError(f"Cannot read transcript {path}: {exc}") from exc


def classify(words: list[WordTimestamp], matcher: ProfanityMatcher) -> list[WordTimestamp]:
    return [replace(w, profane=matcher.matches(w.word)) for w in words]


def save_transcript(path: Path, words: list[WordTimestamp], metadata: dict | None = None) -> None:
    write_json(path, {"metadata": metadata or {}, "words": [asdict(w) for w in words]})


def load_cache(path: Path, duration: float) -> list[WordTimestamp] | None:
    if not path.exists():
        return None
    try:
        return read_transcript(path, duration, require_flags=False)
    except CensorError as exc:
        LOG.warning("Ignoring invalid transcription cache: %s", exc)
        return None
