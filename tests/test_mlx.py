import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from censor.cli import main
from censor.mlx_backend import DEFAULT_MODEL, INITIAL_PROMPT, MLXWhisperBackend, frame_progress, resolve_model
from censor.transcription import cache_key
from censor.utils import CensorError


class MLXTests(unittest.TestCase):
    def test_model_alias_and_local_directory(self):
        self.assertEqual(resolve_model("large-v3-turbo"), DEFAULT_MODEL)
        self.assertEqual(resolve_model("mlx-community/whisper-small-mlx"), "mlx-community/whisper-small-mlx")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(resolve_model(folder), str(Path(folder).resolve()))
        with self.assertRaises(CensorError):
            resolve_model("small")

    def test_progress_adapter_restored_on_error(self):
        original = object()
        module = SimpleNamespace(tqdm=original, FRAMES_PER_SECOND=100)
        seen = []
        with self.assertRaises(KeyboardInterrupt):
            with frame_progress(module, seen.append):
                with module.tqdm.tqdm(total=9000) as bar:
                    bar.update(3000)
                    bar.update(2500)
                    raise KeyboardInterrupt
        self.assertEqual(seen, [30, 55])
        self.assertIs(module.tqdm, original)

    def test_backend_separates_cache_and_preserves_cpu_metadata(self):
        with tempfile.TemporaryDirectory() as folder, patch("importlib.metadata.version", return_value="test"):
            path = Path(folder) / "video"
            path.write_bytes(b"video")
            cpu, metadata = cache_key(path, "model", "ru", "float32", 0)
            gpu, gpu_meta = cache_key(path, "model", "ru", "float32", 0, backend="mlx")
            self.assertNotEqual(cpu, gpu)
            self.assertEqual(metadata["beam_size"], 5)
            self.assertTrue(metadata["vad_filter"])
            self.assertNotIn("mlx_version", metadata)
            self.assertTrue(gpu_meta["vad_filter"])
            self.assertEqual(gpu_meta["backend"], "mlx")
            self.assertEqual(gpu_meta["initial_prompt"], INITIAL_PROMPT)

    def test_unsupported_platform_is_actionable(self):
        with patch("censor.mlx_backend.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(CensorError, "Apple Silicon"):
                MLXWhisperBackend("turbo", "ru").transcribe(Path("audio.wav"), lambda _: None)

    def test_gpu_inference_offline_timestamps_and_cleanup(self):
        mx = SimpleNamespace(gpu="gpu", metal=SimpleNamespace(is_available=lambda: True),
                             stream=Mock(side_effect=lambda _: contextlib.nullcontext()))
        download = Mock(return_value="/cached/model")
        original = object()
        module = SimpleNamespace(tqdm=original, FRAMES_PER_SECOND=100)
        def transcribe(audio, **options):
            self.assertEqual(options["path_or_hf_repo"], "/cached/model")
            self.assertTrue(options["word_timestamps"])
            self.assertTrue(options["fp16"])
            self.assertEqual(options["initial_prompt"], INITIAL_PROMPT)
            with module.tqdm.tqdm() as bar:
                bar.update(1000)
            return {"segments": [{"words": [{"word": " блядь", "start": 2.1, "end": 2.5}]}]}
        module.transcribe = transcribe
        modules = {"mlx": SimpleNamespace(core=mx), "mlx.core": mx,
                   "huggingface_hub": SimpleNamespace(snapshot_download=download)}
        from faster_whisper.vad import SpeechTimestampsMap
        timeline = SpeechTimestampsMap([{"start": 16000, "end": 320000}], 16000)
        with patch.dict("sys.modules", modules), \
             patch("censor.mlx_backend.platform.system", return_value="Darwin"), \
             patch("censor.mlx_backend.platform.machine", return_value="arm64"), \
             patch("censor.mlx_backend.speech_audio", return_value=("speech", timeline)) as speech, \
             patch("censor.mlx_backend.importlib.import_module", return_value=module):
            seen = []
            words = MLXWhisperBackend("turbo", "ru", offline=True).transcribe(Path("audio.wav"), seen.append)
            self.assertTrue(download.call_args.kwargs["local_files_only"])
            mx.stream.assert_called_once_with("gpu")
            self.assertEqual((words[0].word, words[0].start, words[0].end), ("блядь", 3.1, 3.5))
            self.assertEqual(seen, [11])
            self.assertIs(module.tqdm, original)
            speech.return_value = ([], None)
            self.assertEqual(MLXWhisperBackend("turbo", "ru").transcribe(Path("audio.wav"), seen.append), [])
            speech.return_value = ("speech", timeline)
            module.transcribe = Mock(side_effect=RuntimeError("GPU failure"))
            with self.assertRaisesRegex(CensorError, "GPU failure"):
                MLXWhisperBackend("turbo", "ru").transcribe(Path("audio.wav"), seen.append)
            self.assertIs(module.tqdm, original)
            mx.metal.is_available = lambda: False
            with self.assertRaisesRegex(CensorError, "unavailable"):
                MLXWhisperBackend("turbo", "ru").transcribe(Path("audio.wav"), seen.append)

    def test_incompatible_precision_rejected_before_reading_source(self):
        import io
        for args in [("mlx", "int8"), ("faster-whisper", "float16")]:
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(["missing.mov", "--backend", args[0], "--compute-type", args[1]]), 1)
            self.assertIn("supports" if args[0] == "mlx" else "support", output.getvalue())
