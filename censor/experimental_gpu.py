"""Experimental Apple GPU recognizers; shared word/mute/export pipeline stays unchanged."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

from .models import WordTimestamp
from .model_downloads import ModelDownloadRequired
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


def prepare(model, offline=True):
    """Resolve pinned assets before inference; all runtime loaders receive local paths."""
    backend, repo, revision = MODELS[model]
    if backend == "gigaam-mps":
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
        folder = Path(os.environ.get("BLEEP_MODEL_CACHE", str(ROOT / ".cache"))) / "gigaam"
        files = [folder / f"{repo}.ckpt", folder / f"{repo}_tokenizer.model"]
        if not offline:
            from gigaam import _download_model, _download_tokenizer
            _download_model(repo, str(folder))
            _download_tokenizer(repo, str(folder))
        if not all(path.is_file() for path in files):
            raise ModelDownloadRequired("GigaAM weights are not cached. Enable first-time model download.")
        return [str(folder)]
    from huggingface_hub import snapshot_download
    assets = [(repo, revision)] + ([ALIGNER] if model == "qwen3-asr" else [])
    return [snapshot_download(name, revision=rev, local_files_only=offline,
                              allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.vocab"])
            for name, rev in assets]


def cache_identity(source, model, audio_index, progress=None, language="ru"):
    backend, repo, revision = MODELS[model]
    package = "gigaam" if backend == "gigaam-mps" else backend
    try:
        version = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError as exc:
        raise CensorError("Experimental GPU dependencies are missing. Run scripts/setup-experimental-gpu.sh.") from exc
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
    if model == "qwen3-asr":
        metadata.update(aligner_model=ALIGNER[0], aligner_revision=ALIGNER[1])
    if backend == "gigaam-mps":
        metadata["backend_revision"] = "7447938d791c4f3e643386ee22c33777004293a5"
    # Keep existing Russian benchmark caches usable; separate English detection runs.
    if language != "ru" and backend == "parakeet-mlx":
        metadata["detection_language"] = language
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
    def __init__(self, model, assets, language="ru"):
        if language not in {"ru", "en"} or (model == "gigaam-v3" and language != "ru"):
            raise CensorError("Unsupported language for this model.")
        self.language = language
        self.model = model
        self.assets = assets

    def transcribe(self, audio, progress):
        if self.model == "gigaam-v3":
            return self.gigaam(audio, progress)
        import mlx.core as mx
        if not mx.metal.is_available():
            raise CensorError("Apple Metal GPU is unavailable; no CPU fallback is used.")
        mx.set_default_device(mx.gpu)
        mx.random.seed(0)
        with mx.stream(mx.gpu):
            if self.model.startswith("parakeet-"):
                from parakeet_mlx import from_pretrained
                model = from_pretrained(self.assets[0], dtype=mx.bfloat16)
                result = model.transcribe(audio, chunk_duration=120, overlap_duration=15,
                                          chunk_callback=lambda current, total: progress(current / 16000))
                return merge_subwords(result.tokens)
            from mlx_qwen3_asr import transcribe
            result = transcribe(str(audio), model=self.assets[0], forced_aligner=self.assets[1],
                                language={"ru": "Russian", "en": "English"}[self.language], return_timestamps=True, return_chunks=True,
                                on_progress=lambda event: progress(event.get("processed_audio_sec", 0)))
            if any(chunk.get("truncated") for chunk in (result.chunks or [])):
                raise CensorError("Qwen reached its token limit; refusing an incomplete transcript.")
            return [WordTimestamp(item["text"], item["start"], item["end"]) for item in result.segments or []]

    def gigaam(self, audio, progress):
        # Explicit MPS and no operator fallback: unsupported GPU operations fail visibly.
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
        import torch
        import gigaam
        import soundfile as sf
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        if not torch.backends.mps.is_available():
            raise CensorError("Apple MPS GPU is unavailable; no CPU fallback is used.")
        torch.manual_seed(0)
        model = gigaam.load_model("v3_e2e_rnnt", device="mps", fp16_encoder=False,
                                  use_flash=False, download_root=self.assets[0])
        data = decode_audio(str(audio), sampling_rate=16000)
        chunks = get_speech_timestamps(data, VadOptions(max_speech_duration_s=20))
        words = []
        with tempfile.TemporaryDirectory(prefix="bleep-gigaam-") as folder:
            path = Path(folder) / "chunk.wav"
            for chunk in chunks:
                sf.write(path, data[chunk["start"]:chunk["end"]], 16000, subtype="FLOAT")
                result = model.transcribe(str(path), word_timestamps=True)
                offset = chunk["start"] / 16000
                words.extend(WordTimestamp(w.text, w.start + offset, w.end + offset) for w in result.words or [])
                progress(chunk["end"] / 16000)
        torch.mps.synchronize()
        return words
