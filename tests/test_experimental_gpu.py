import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from censor.experimental_gpu import ExperimentalGPUBackend, MODELS, cache_identity, merge_subwords, prepare
from censor.utils import CensorError


class ExperimentalGPUTests(unittest.TestCase):
    def test_bundled_gigaam_uses_writable_model_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'BLEEP_MODEL_CACHE': folder}):
            models = Path(folder) / 'gigaam'
            models.mkdir()
            (models / 'v3_e2e_rnnt.ckpt').write_bytes(b'weights')
            (models / 'v3_e2e_rnnt_tokenizer.model').write_bytes(b'tokenizer')
            self.assertEqual(prepare('gigaam-v3', offline=True), [str(models)])

    def test_subword_pieces_become_one_word_before_profanity_matching(self):
        pieces = [SimpleNamespace(text=text, start=start, end=end) for text, start, end in [
            (" Е", 1, 1.1), ("б", 1.1, 1.15), ("ать", 1.15, 1.4), (",", 1.4, 1.4),
            (" друзья", 2, 2.5), ("!", 2.5, 2.5), ("▁Привет", 3, 3.4)]]
        words = merge_subwords(pieces)
        self.assertEqual([(w.word, w.start, w.end) for w in words],
                         [("Ебать,", 1, 1.4), ("друзья!", 2, 2.5), ("Привет", 3, 3.4)])

    def test_cache_identity_separates_models_tracks_and_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.wav"
            source.write_bytes(b"source")
            with patch('censor.experimental_gpu.importlib.metadata.version', return_value='test'):
                identities = [cache_identity(source, name, index) for name in MODELS for index in (0, 1)]
                self.assertEqual(len({key for key, _ in identities}), 8)
                key, meta = cache_identity(source, 'parakeet-v3', 0)
                with patch.dict(MODELS, {'parakeet-v3': ('parakeet-mlx', 'same-name', 'new-revision')}):
                    changed, _ = cache_identity(source, 'parakeet-v3', 0)
                self.assertNotEqual(key, changed)
                self.assertEqual(meta['device'], 'GPU (Metal)')
                _, qwen = cache_identity(source, 'qwen3-asr', 0)
                self.assertIn('aligner_revision', qwen)

    def test_offline_preparation_cannot_download_gigaam(self):
        with tempfile.TemporaryDirectory() as folder, patch('censor.experimental_gpu.ROOT', Path(folder)):
            with self.assertRaisesRegex(CensorError, 'not cached'):
                prepare('gigaam-v3', offline=True)

    def test_pinned_hf_assets_are_requested_offline(self):
        with patch('huggingface_hub.snapshot_download', return_value='/cached') as download:
            self.assertEqual(prepare('qwen3-asr'), ['/cached', '/cached'])
            self.assertEqual(download.call_count, 2)
            self.assertTrue(all(call.kwargs['local_files_only'] for call in download.call_args_list))
            self.assertTrue(all(len(call.kwargs['revision']) == 40 for call in download.call_args_list))

    def test_english_and_russian_caches_are_separate(self):
        with tempfile.TemporaryDirectory() as folder, patch('censor.experimental_gpu.importlib.metadata.version', return_value='test'):
            source = Path(folder) / 'source.wav'
            source.write_bytes(b'source')
            for model in ('parakeet-v3', 'parakeet-ultra', 'qwen3-asr'):
                ru, _ = cache_identity(source, model, 0)
                en, metadata = cache_identity(source, model, 0, language='en')
                self.assertNotEqual(ru, en)
                self.assertEqual(metadata.get('detection_language', metadata['language']), 'en')

    def test_qwen_receives_selected_language(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        mx = Mock()
        mx.metal.is_available.return_value = True
        mx.stream.return_value = nullcontext()
        transcribe = Mock(return_value=SimpleNamespace(chunks=[], segments=[dict(text='fuck', start=1, end=1.2)]))
        modules = {'mlx': SimpleNamespace(core=mx), 'mlx.core': mx,
                   'mlx_qwen3_asr': SimpleNamespace(transcribe=transcribe)}
        with patch.dict('sys.modules', modules):
            words = ExperimentalGPUBackend('qwen3-asr', ['/model', '/aligner'], language='en').transcribe(Path('audio.wav'), lambda _: None)
        self.assertEqual(transcribe.call_args.kwargs['language'], 'English')
        self.assertEqual(words[0].word, 'fuck')
