"""Additional Apple Silicon recognizers with explicit CPU/GPU device selection."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

from .models import WordTimestamp
from .speech_chunks import CONTEXT_SECONDS, append_window_words, speech_windows
from .model_downloads import ModelDownloadRequired
from .download_progress import byte_progress_bar, download_snapshot
from .transcription import file_hash
from .utils import CensorError

MODELS = {
    "parakeet-v3": ("parakeet-mlx", "mlx-community/parakeet-tdt-0.6b-v3", "ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15"),
    "parakeet-ultra": ("parakeet-mlx", "selcukkubur/parakeet-ultra-mlx", "b554592c50b2a48471add2daa3d46fa9f00fef5e"),
    "qwen3-asr": ("mlx-qwen3-asr", "Qwen/Qwen3-ASR-1.7B", "7278e1e70fe206f11671096ffdd38061171dd6e5"),
    "gigaam-v3": ("gigaam-mps", "v3_e2e_rnnt", "2730de7545ac43ad256485a462b0a27a"),
}
ALIGNER = ("Qwen/Qwen3-ForcedAligner-0.6B", "c7cbfc2048c462b0d63a45797104fc9db3ad62b7")
BACKENDS = {value[0] for value in MODELS.values()}
ROOT = Path(__file__).resolve().parents[1]


def prepare(model, offline=True, progress=None):
    """Resolve pinned assets before inference; all runtime loaders receive local paths."""
    notify = progress or (lambda label, fraction: None)
    backend, repo, revision = MODELS[model]
    if backend == "gigaam-mps":
        notify("Checking GigaAM model", 0)
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
        folder = Path(os.environ.get("BLEEP_MODEL_CACHE", str(ROOT / ".cache"))) / "gigaam"
        files = [folder / f"{repo}.ckpt", folder / f"{repo}_tokenizer.model"]
        if not offline:
            import gigaam
            # GigaAM's pinned downloader exposes its byte counts through module tqdm.
            # Each desktop worker prepares one model at a time; restore on every exit.
            for path, name, download in [(files[0], "GigaAM", gigaam._download_model),
                                         (files[1], "GigaAM tokenizer", gigaam._download_tokenizer)]:
                if path.is_file():
                    continue
                notify(f"Connecting to download {name}", 0)
                original = gigaam.tqdm
                try:
                    gigaam.tqdm = byte_progress_bar(f"Downloading {name}", notify)
                    download(repo, str(folder))
                finally:
                    gigaam.tqdm = original
        if not all(path.is_file() for path in files):
            raise ModelDownloadRequired("GigaAM weights are not cached. Enable first-time model download.")
        aligner = prepare_hub_asset(*ALIGNER, "Qwen ForcedAligner", offline, notify)
        return [str(folder), aligner]
    name = {"parakeet-v3": "Parakeet v3", "parakeet-ultra": "Parakeet Ultra", "qwen3-asr": "Qwen3 ASR"}[model]
    assets = [(repo, revision, name)] + ([(*ALIGNER, "Qwen ForcedAligner")] if model == "qwen3-asr" else [])
    return [prepare_hub_asset(repo, rev, name, offline, notify) for repo, rev, name in assets]


def prepare_hub_asset(repo, revision, name, offline, notify):
    from huggingface_hub import snapshot_download
    return download_snapshot(snapshot_download, repo, name, offline, notify, revision=revision,
                             allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.vocab"])


def cache_identity(source, model, audio_index, progress=None, language="ru", device="gpu"):
    if device not in {"cpu", "gpu"}:
        raise CensorError("Choose CPU or GPU for recognition.")
    backend, repo, revision = MODELS[model]
    package = "gigaam" if backend == "gigaam-mps" else backend
    try:
        version = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError as exc:
        raise CensorError("Additional recognition dependencies are missing. Run scripts/setup-experimental-gpu.sh.") from exc
    metadata = dict(schema=1, adapter_version=1, source_sha256=file_hash(source, progress),
                    backend=backend, backend_version=version, model=repo, model_revision=revision,
                    model_choice=model, audio_index=audio_index, word_timestamps=True,
                    language=language if model != "parakeet-v3" and model != "parakeet-ultra" else "auto",
                    compute_type="float32 weights / float16 autocast" if backend == "gigaam-mps" else "bfloat16" if backend == "parakeet-mlx" else "float16",
                    device="GPU (MPS)" if backend == "gigaam-mps" else "GPU (Metal)",
                    chunk_seconds=20 if backend == "gigaam-mps" else 120 if backend == "parakeet-mlx" else 30,
                    overlap_seconds=15 if backend == "parakeet-mlx" else 0,
                    vad_filter=backend == "gigaam-mps",
                    decoder="greedy", seed=0)
    for dependency in ["torch" if backend == "gigaam-mps" else "mlx", "numpy", "faster-whisper"]:
        metadata[dependency + "_version"] = importlib.metadata.version(dependency)
    if model in {"qwen3-asr", "gigaam-v3"}:
        metadata.update(aligner_model=ALIGNER[0], aligner_revision=ALIGNER[1])
    if backend == "gigaam-mps":
        metadata["backend_revision"] = "7447938d791c4f3e643386ee22c33777004293a5"
        metadata.update(adapter_version=4, context_seconds=CONTEXT_SECONDS,
                        overlap_seconds=2 * CONTEXT_SECONDS, stitching="midpoint-ownership-v1",
                        alignment="qwen-bounded-retry-v2",
                        mlx_version=importlib.metadata.version("mlx"),
                        aligner_backend_version=importlib.metadata.version("mlx-qwen3-asr"))
    # Keep existing Russian benchmark caches usable; separate English detection runs.
    if language != "ru" and backend == "parakeet-mlx":
        metadata["detection_language"] = language
    if device == "cpu":
        metadata.update(device="CPU", compute_type="float32", device_adapter_version=1)
    key = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return key, metadata


def merge_subwords(tokens):
    """Parakeet exposes SentencePiece pieces, not words. Preserve lexical boundaries."""
    words = []
    for token in tokens:
        text = token.text.replace("▁", " ")
        if not text:
            continue
        if not words or text[0].isspace():
            if text.strip():
                words.append(WordTimestamp(text.strip(), float(token.start), float(token.end)))
        else:
            previous = words[-1]
            words[-1] = WordTimestamp(previous.word + text, previous.start, max(previous.end, float(token.end)))
    return words


class ExperimentalGPUBackend:
    def __init__(self, model, assets, language="ru", stage=None, device="gpu"):
        if device not in {"cpu", "gpu"}:
            raise CensorError("Choose CPU or GPU for recognition.")
        self.device = device
        if language not in {"ru", "en"} or (model == "gigaam-v3" and language != "ru"):
            raise CensorError("Unsupported language for this model.")
        self.language = language
        self.model = model
        self.assets = assets
        self.metrics = {}
        self.stage = stage or (lambda _: None)

    def transcribe(self, audio, progress):
        if self.model == "gigaam-v3":
            return self.gigaam(audio, progress)
        import mlx.core as mx
        if self.device == "gpu" and not mx.metal.is_available():
            raise CensorError("Apple Metal GPU is unavailable; no CPU fallback is used.")
        device = mx.cpu if self.device == "cpu" else mx.gpu
        mx.set_default_device(device)
        if self.device == "cpu":
            # CPU JIT emits unsigned dylibs and needs a compiler on the user's
            # Mac. Eager execution works in the signed release runtime too.
            mx.disable_compile()
        mx.random.seed(0)
        with mx.stream(device):
            if self.model.startswith("parakeet-"):
                self.stage("Loading Parakeet model")
                from parakeet_mlx import from_pretrained
                dtype = mx.float32 if self.device == "cpu" else mx.bfloat16
                model = from_pretrained(self.assets[0], dtype=dtype)
                self.stage("Recognizing speech")
                result = model.transcribe(audio, dtype=dtype, chunk_duration=120, overlap_duration=15,
                                          chunk_callback=lambda current, total: progress(current / 16000))
                return merge_subwords(result.tokens)
            from mlx_qwen3_asr import transcribe
            self.stage("Loading Qwen model")
            result = transcribe(str(audio), model=self.assets[0], forced_aligner=self.assets[1],
                                dtype=mx.float32 if self.device == "cpu" else mx.float16,
                                language={"ru": "Russian", "en": "English"}[self.language], return_timestamps=True, return_chunks=True,
                                on_progress=lambda event: progress(event.get("processed_audio_sec", 0)))
            if any(chunk.get("truncated") for chunk in (result.chunks or [])):
                raise CensorError("Qwen reached its token limit; refusing an incomplete transcript.")
            return [WordTimestamp(item["text"], item["start"], item["end"]) for item in result.segments or []]

    def gigaam(self, audio, progress):
        # Honor the selected device; GPU operations never silently fall back to CPU.
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
        import torch
        import gigaam
        import soundfile as sf
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        from .word_alignment import WordAligner
        if self.device == "gpu" and not torch.backends.mps.is_available():
            raise CensorError("Apple MPS GPU is unavailable; no CPU fallback is used.")
        torch.manual_seed(0)
        self.stage("Loading GigaAM model")
        model = gigaam.load_model("v3_e2e_rnnt", device="cpu" if self.device == "cpu" else "mps", fp16_encoder=False,
                                  use_flash=False, download_root=self.assets[0])
        self.stage("Loading word alignment model")
        aligner = WordAligner(self.assets[1], device=self.device)
        self.stage("Preparing speech detection")
        data = decode_audio(str(audio), sampling_rate=16000)
        chunks = get_speech_timestamps(data, VadOptions(max_speech_duration_s=20))
        words = []
        self.stage("Recognizing speech")
        with tempfile.TemporaryDirectory(prefix="bleep-gigaam-") as folder:
            path = Path(folder) / "chunk.wav"
            for window in speech_windows(chunks, len(data)):
                segment = data[window.start:window.end]
                sf.write(path, segment, 16000, subtype="FLOAT")
                result = model.transcribe(str(path), word_timestamps=True)
                offset = window.start / 16000
                native = [WordTimestamp(w.text, w.start, w.end) for w in result.words or []]
                current = [WordTimestamp(w.word, w.start + offset, w.end + offset)
                           for w in aligner.align(segment, native)]
                append_window_words(words, current, window)
                progress(window.own_end)
        if self.device == "gpu":
            torch.mps.synchronize()
        self.metrics['word_alignment'] = aligner.metrics
        return words
