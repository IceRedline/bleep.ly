import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from censor.models import WordTimestamp
from censor.profanity import ProfanityMatcher
from censor.transcription import FasterWhisperBackend, cache_key, classify, load_cache, save_transcript
from censor.utils import CensorError


class TranscriptionTests(unittest.TestCase):
    def test_cache_invalidation_and_reclassification(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.mov"
            source.write_bytes(b"one")
            key, meta = cache_key(source, "large-v3-turbo", "ru", "int8", 1)
            self.assertEqual(key, cache_key(source, "large-v3-turbo", "ru", "int8", 1)[0])
            self.assertNotEqual(key, cache_key(source, "small", "ru", "int8", 1)[0])
            self.assertNotEqual(key, cache_key(source, "large-v3-turbo", "en", "int8", 1)[0])
            self.assertNotEqual(key, cache_key(source, "large-v3-turbo", "ru", "int8", 2)[0])
            source.write_bytes(b"two")
            self.assertNotEqual(key, cache_key(source, "large-v3-turbo", "ru", "int8", 1)[0])
            cache = Path(folder) / "cache.json"
            save_transcript(cache, [WordTimestamp("бля", 0, 1)], meta)
            words = load_cache(cache, 2)
            self.assertTrue(classify(words, ProfanityMatcher(["бля"]))[0].profane)
            self.assertFalse(classify(words, ProfanityMatcher([]))[0].profane)
            cache.write_text("broken")
            with self.assertLogs(level="WARNING"):
                self.assertIsNone(load_cache(cache, 2))

    def test_backend_word_timestamps_and_lazy_errors(self):
        from unittest.mock import Mock
        factory = Mock()
        factory.return_value.transcribe.return_value = (iter([SimpleNamespace(end=1,
             words=[SimpleNamespace(word=" блядь", start=.1, end=.5)])]), None)
        telemetry = Mock()
        with patch.dict("sys.modules", {"faster_whisper": SimpleNamespace(WhisperModel=factory),
                                        "onnxruntime": SimpleNamespace(disable_telemetry_events=telemetry)}):
            backend = FasterWhisperBackend("large-v3-turbo", "ru", offline=True)
            words = backend.transcribe(Path("audio.wav"), lambda _: None)
            self.assertEqual(words[0].word, "блядь")
            self.assertTrue(factory.return_value.transcribe.call_args.kwargs["word_timestamps"])
            self.assertEqual(factory.call_args.kwargs["device"], "cpu")
            telemetry.assert_called_once()
            def failing():
                raise RuntimeError("inference failed")
                yield
            factory.return_value.transcribe.return_value = (failing(), None)
            with self.assertRaisesRegex(CensorError, "inference failed"):
                backend.transcribe(Path("audio.wav"), lambda _: None)
