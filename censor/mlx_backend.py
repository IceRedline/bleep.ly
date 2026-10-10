"""Optional Apple GPU inference; rendering is shared with the CPU backend."""
import importlib
import platform
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from .models import WordTimestamp
from .utils import CensorError

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
# Whisper often omits conversational profanity with greedy decoding. Vocabulary
# context encourages verbatim recognition; it is not injected into the result.
INITIAL_PROMPT = "Разговорная русская речь. Блядь, блять, бля, нахуй, охуеть, пиздец, ебать."


def speech_audio(audio: Path):
    """Use the CPU backend's VAD and retain a map to the original timeline."""
    import numpy as np
    import onnxruntime
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import SpeechTimestampsMap, get_speech_timestamps

    onnxruntime.disable_telemetry_events()
    data = decode_audio(str(audio), sampling_rate=16000)
    chunks = get_speech_timestamps(data)
    if not chunks:
        return np.array([], dtype=np.float32), None
    speech = np.concatenate([data[item["start"]:item["end"]] for item in chunks])
    return speech, SpeechTimestampsMap(chunks, 16000)


def resolve_model(model: str) -> str:
    if Path(model).is_dir():
        return str(Path(model).resolve())
    if model == "large-v3":
        return "mlx-community/whisper-large-v3-mlx"
    if model in {"large-v3-turbo", "turbo"}:
        return DEFAULT_MODEL
    if "/" not in model:
        raise CensorError("MLX requires an MLX model directory or Hugging Face repo ID; "
                          "use --model mlx-community/whisper-large-v3-turbo.")
    return model


@contextmanager
def frame_progress(module, callback: Callable[[float], None]):
    """Adapt mlx-whisper 0.4.3's frame counter without splitting speech windows.

    Scoped to its transcribe module, restored even on cancellation. The CLI runs
    one inference at a time; this adapter must not be used concurrently.
    """
    original = module.tqdm

    class Counter:
        def __init__(self, *args, **kwargs):
            self.frames = 0

        def __enter__(self):
            return self

        def update(self, amount):
            self.frames += amount
            callback(self.frames / module.FRAMES_PER_SECOND)

        def __exit__(self, *args):
            return False

    module.tqdm = SimpleNamespace(tqdm=Counter)
    try:
        yield
    finally:
        module.tqdm = original


class MLXWhisperBackend:
    def __init__(self, model: str, language: str, compute_type: str = "float16", offline: bool = False):
        self.model = resolve_model(model)
        self.language = language
        self.compute_type = compute_type
        self.offline = offline

    def transcribe(self, audio: Path, progress: Callable[[float], None]) -> list[WordTimestamp]:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise CensorError("MLX GPU requires Apple Silicon macOS and an ARM64 Python. "
                              "Use --backend faster-whisper on other systems.")
        try:
            import mlx.core as mx
            from huggingface_hub import snapshot_download
            module = importlib.import_module("mlx_whisper.transcribe")
        except ImportError as exc:
            raise CensorError("MLX is not installed. Run: pip install -r requirements-mlx.txt") from exc
        try:
            if not mx.metal.is_available():
                raise CensorError("Apple Metal GPU is unavailable. Run in a local macOS terminal "
                                  "with GPU access, or use --backend faster-whisper.")
            speech, timeline = speech_audio(audio)
            if timeline is None:
                return []
            model = self.model
            if not Path(model).is_dir():
                # Resolve first so --offline also applies to MLX's internal loader.
                model = snapshot_download(model, local_files_only=self.offline,
                                          allow_patterns=["config.json", "*.safetensors", "*.npz"])
            with mx.stream(mx.gpu), frame_progress(module, lambda seconds: progress(timeline.get_original_time(seconds))):
                result = module.transcribe(speech, path_or_hf_repo=model,
                                           language=self.language, word_timestamps=True,
                                           initial_prompt=INITIAL_PROMPT if self.language == "ru" else None,
                                           fp16=self.compute_type == "float16", verbose=None)
            words = []
            for segment in result["segments"]:
                for word in segment.get("words", []):
                    if not word["word"].strip():
                        continue
                    # Both boundaries use the same VAD chunk, including at joins.
                    chunk = timeline.get_chunk_index((word["start"] + word["end"]) / 2)
                    words.append(WordTimestamp(word["word"].strip(),
                                               timeline.get_original_time(word["start"], chunk),
                                               timeline.get_original_time(word["end"], chunk)))
            return words
        except CensorError:
            raise
        except Exception as exc:
            raise CensorError(f"MLX transcription failed: {exc}. Check the MLX model and free memory. "
                              "The first model download requires network access; --offline forbids it.") from exc
