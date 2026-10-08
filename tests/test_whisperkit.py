import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from censor.benchmark import compare
from censor.models import WordTimestamp
from censor.utils import CensorError
from censor.whisperkit_backend import (WhisperKitBackend, prepare_assets, cache_identity,
    COMPONENTS, MODEL, MODEL_REVISION, TOKENIZER_REVISION, download_progress_bar)


class WhisperKitTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.work = Path(self.folder.name)

    def install_dummy_assets(self):
        for component in COMPONENTS:
            for name in ('weights/weight.bin', 'coremldata.bin', 'model.mil'):
                path = self.work / component / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('dummy')
        for name in ('tokenizer.json', 'tokenizer_config.json'):
            (self.work / name).write_text('{}')
        (self.work / 'bleep-model.json').write_text(json.dumps(dict(
            model=MODEL, revision=MODEL_REVISION, tokenizer_revision=TOKENIZER_REVISION)))

    def test_offline_requires_complete_pinned_assets(self):
        with patch('huggingface_hub.snapshot_download', side_effect=AssertionError('network')):
            with self.assertRaises(CensorError):
                prepare_assets(self.work)
            self.install_dummy_assets()
            prepare_assets(self.work)
            (self.work / 'bleep-model.json').write_text('{}')
            with self.assertRaises(CensorError):
                prepare_assets(self.work)
            self.install_dummy_assets()
            (self.work / COMPONENTS[0] / 'model.mil').write_text('')
            with self.assertRaises(CensorError):
                prepare_assets(self.work)

    def test_byte_progress_counts_reconstruction_not_xet_transfer_twice(self):
        updates = []
        bar_type = download_progress_bar(updates.append)
        with bar_type(total=100, initial=20, unit='B', disable=True,
                      desc='weights: reconstructing file', name='hub') as bar:
            bar.update(30)
            bar.update(50)
        self.assertEqual(updates, [20, 50, 100])
        with bar_type(total=100, unit='B', desc='weights: downloading bytes') as transfer:
            transfer.update(100)
        self.assertEqual(updates, [20, 50, 100])

    def test_first_install_reports_download_install_and_ready_then_reuses_assets(self):
        from huggingface_hub import RepoFile
        entries = [RepoFile(path=f'{MODEL}/{component}/{name}', size=100, oid='test')
                   for component in COMPONENTS for name in ('weights/weight.bin', 'coremldata.bin', 'model.mil')]
        tokens = [RepoFile(path=name, size=100, oid='test') for name in ('tokenizer.json', 'tokenizer_config.json')]
        events = []
        def tree(repo, **kwargs):
            return entries if repo == 'argmaxinc/whisperkit-coreml' else tokens
        def download(repo, name, **kwargs):
            with kwargs['tqdm_class'](total=100, unit='B', desc=name) as bar:
                bar.update(40)
                bar.update(60)
            path = Path(kwargs['local_dir']) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * 100)
            return str(path)
        with patch('huggingface_hub.HfApi.list_repo_tree', side_effect=tree), \
             patch('huggingface_hub.hf_hub_download', side_effect=download) as downloads, \
             patch('censor.whisperkit_backend.time.monotonic', side_effect=range(1000)):
            prepare_assets(self.work, offline=False, progress=lambda *e: events.append(e))
        self.assertEqual(downloads.call_count, 11)
        self.assertTrue(any(label.startswith('Downloading WhisperKit') and 0 < value < .98 for label, value in events))
        self.assertIn(('Installing WhisperKit model', .99), events)
        self.assertEqual(events[-1], ('WhisperKit model ready', 1))
        self.assertEqual([e[1] for e in events], sorted(e[1] for e in events))
        with patch('huggingface_hub.HfApi.list_repo_tree', side_effect=AssertionError('network')):
            cached_events = []
            prepare_assets(self.work, progress=lambda *e: cached_events.append(e))
            self.assertEqual(cached_events, [])

    def test_download_failure_never_reports_ready_or_marks_assets_installed(self):
        from huggingface_hub import RepoFile
        entry = RepoFile(path=f'{MODEL}/{COMPONENTS[0]}/weights/weight.bin', size=100, oid='test')
        events = []
        with patch('huggingface_hub.HfApi.list_repo_tree', return_value=[entry]), \
             patch('huggingface_hub.hf_hub_download', side_effect=OSError('connection lost')):
            with self.assertRaisesRegex(OSError, 'connection lost'):
                prepare_assets(self.work, offline=False, progress=lambda *e: events.append(e))
        self.assertFalse((self.work / 'bleep-model.json').exists())
        self.assertFalse(any(value == 1 for _, value in events))

    def helper(self, body):
        import sys
        path = self.work / 'helper with spaces'
        path.write_text('#!' + sys.executable + '\n' + body)
        path.chmod(0o700)
        return path

    def test_subprocess_contract_and_failure_without_fallback(self):
        helper = self.helper('''import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
print(json.dumps(dict(event='stage', stage='loading')))
print(json.dumps(dict(event='progress', seconds=1.2)))
Path(request['output']).write_text(json.dumps(dict(words=[dict(word='бля',start=1,end=1.2)], load_seconds=3)))
''')
        stages, progress = [], []
        backend = WhisperKitBackend(helper, self.work, stages.append)
        self.assertEqual(backend.transcribe(self.work / 'audio.wav', progress.append), [WordTimestamp('бля', 1, 1.2)])
        self.assertEqual(stages, ['loading'])
        self.assertEqual(progress, [1.2])
        self.assertEqual(backend.metrics['load_seconds'], 3)
        self.helper("import sys\nprint('{\"event\":\"error\",\"message\":\"bad model\"}')\nsys.exit(2)\n")
        with self.assertRaisesRegex(CensorError, 'bad model.*No fallback'):
            backend.transcribe(self.work / 'audio.wav', progress.append)
        with self.assertRaisesRegex(CensorError, 'helper is missing'):
            WhisperKitBackend(self.work / 'missing', self.work)

    def test_cache_identity_separates_model_helper_and_audio_track(self):
        self.install_dummy_assets()
        source = self.work / 'audio.wav'; source.write_bytes(b'audio')
        helper = self.helper('pass\n')
        first, metadata = cache_identity(source, self.work, helper, 1)
        self.assertEqual(metadata['backend'], 'whisperkit')
        self.assertEqual(first, cache_identity(source, self.work, helper, 1)[0])
        self.assertNotEqual(first, cache_identity(source, self.work, helper, 2)[0])
        self.helper('print(1)\n')
        self.assertNotEqual(first, cache_identity(source, self.work, helper, 1)[0])
        before_model_change = cache_identity(source, self.work, helper, 1)[0]
        (self.work / COMPONENTS[0] / 'model.mil').write_text('changed model')
        self.assertNotEqual(before_model_change, cache_identity(source, self.work, helper, 1)[0])


class ComparisonTests(unittest.TestCase):
    def word(self, text, start, flag=True):
        return dict(word=text, start=start, end=start + .2, profane=flag)

    def test_spelling_variants_match_by_time_but_missing_words_still_count(self):
        ref = dict(words=[self.word('Блять!', 1), self.word('блять', 4)])
        hyp = dict(words=[self.word('блядь', 1.1), self.word('блять', 8)])
        result = compare(ref, hyp)
        self.assertEqual(result['recall'], .5)
        self.assertEqual(result['precision'], .5)
        self.assertAlmostEqual(result['mean_edge_error_seconds'], .1)
        self.assertEqual(result['missed'][0]['start'], 4)

    def test_one_candidate_cannot_cover_two_occurrences(self):
        ref = dict(words=[self.word('бля', 1), self.word('бля', 1.3)])
        hyp = dict(words=[self.word('бля', 1.1)])
        self.assertEqual(compare(ref, hyp)['matched_explicit'], 1)

    def test_empty_and_perfect(self):
        self.assertIsNone(compare(dict(words=[]), dict(words=[]))['recall'])
        ref = dict(words=[self.word('Привет!', 1, False), self.word('бля', 2)])
        result = compare(ref, ref)
        self.assertEqual(result['lexical_disagreement_rate'], 0)
        self.assertEqual(result['recall'], 1)
        self.assertEqual(result['mean_edge_error_seconds'], 0)
