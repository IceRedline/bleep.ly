import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('speedtest', Path(__file__).resolve().parents[1] / 'scripts/speedtest.py')
speedtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speedtest)


class SpeedtestTests(unittest.TestCase):
    def test_bundled_reference_is_exact_original_fixture(self):
        manifest = json.loads(speedtest.MANIFEST.read_text())
        self.assertEqual(speedtest.sha256(speedtest.REFERENCE_AUDIO), manifest['audio_file_sha256'])
        self.assertEqual(speedtest.validate_audio(speedtest.REFERENCE_AUDIO, manifest), manifest['audio_file_sha256'])

    def test_source_archive_has_fingerprint_without_inheriting_parent_git_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'censor').mkdir()
            module = root / 'censor/example.py'; module.write_text('first')
            with patch.object(speedtest, 'ROOT', root), patch.object(speedtest, 'capture', return_value=str(root.parent)):
                first = speedtest.source_info()
                self.assertIsNone(first['git_commit'])
                self.assertIsNone(first['git_dirty'])
                module.write_text('changed')
                self.assertNotEqual(first['source_sha256'], speedtest.source_info()['source_sha256'])

    def test_first_observed_is_excluded_and_partial_or_failed_runs_are_not_a_score(self):
        runs = [dict(mode='cpu', iteration=i, status='ok', wall_seconds=t)
                for i, t in enumerate([600, 12, 10, 11])]
        result = speedtest.summarize(runs, 3, 100)
        self.assertEqual(result['cpu']['first_wall_seconds'], 600)
        self.assertEqual(result['cpu']['median_seconds'], 11)
        self.assertEqual(result['cpu']['realtime_factor'], .11)
        self.assertEqual(result['gpu']['status'], 'incomplete')
        self.assertNotIn('median_seconds', speedtest.summarize(runs[:3], 3, 100)['cpu'])
        runs[-1]['status'] = 'error'
        self.assertEqual(speedtest.summarize(runs, 3, 100)['cpu']['status'], 'error')
        self.assertNotIn('median_seconds', speedtest.summarize(runs, 3, 100)['cpu'])

    def test_wrong_fixture_rejected_before_inference(self):
        manifest = dict(sample_rate=16000, channels=1, samples=2, audio_pcm_sha256='bad')
        probe = json.dumps(dict(streams=[dict(codec_type='audio', codec_name='flac', sample_rate='16000', channels=1)]))
        with patch.object(speedtest, 'capture', return_value=probe), \
             patch.object(speedtest.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=b'1234')):
            with self.assertRaisesRegex(ValueError, 'audio mismatch'):
                speedtest.validate_audio(Path('input.flac'), manifest)
        probe = json.dumps(dict(streams=[dict(codec_type='video')]))
        with patch.object(speedtest, 'capture', return_value=probe):
            with self.assertRaisesRegex(ValueError, 'audio-only'):
                speedtest.validate_audio(Path('video.mp4'), manifest)

    def worker(self, body):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        package = root / 'censor'; package.mkdir()
        (package / '__init__.py').touch()
        (package / 'desktop.py').write_text(body)
        return root

    def test_cache_hits_and_failed_workers_never_become_scores(self):
        root = self.worker("import json\nprint(json.dumps(dict(event='result',cache_hit=True)))\n")
        with patch.object(speedtest, 'ROOT', root):
            result = speedtest.run_worker({}, root / 'cached', 10)
        self.assertEqual(result['code'], 'unexpected_cache_hit')
        (root / 'censor/desktop.py').write_text("import sys,json\nprint(json.dumps(dict(event='error',code='native_failed',message='/private/path')))\nsys.exit(2)\n")
        with patch.object(speedtest, 'ROOT', root):
            result = speedtest.run_worker({}, root / 'failed', 10)
        self.assertEqual(result['code'], 'native_failed')
        self.assertNotIn('/private/path', json.dumps(result))

    def test_worker_timeout_is_recorded(self):
        root = self.worker('import time\ntime.sleep(60)\n')
        with patch.object(speedtest, 'ROOT', root):
            result = speedtest.run_worker({}, root / 'timeout', .1)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 'timeout')

    def test_edited_model_weights_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'models/cpu'; folder.mkdir(parents=True)
            weights = folder / 'model.bin'; weights.write_bytes(b'first')
            speedtest.save(root / 'cpu-assets.json', dict(revision='pinned', files=speedtest.model_fingerprints(folder)))
            manifest = dict(models=dict(cpu=dict(revision='pinned')))
            with patch.object(speedtest, 'WORK', root):
                speedtest.verify_assets('cpu', manifest, root)
                weights.write_bytes(b'other')
                with self.assertRaisesRegex(ValueError, 'weights changed'):
                    speedtest.verify_assets('cpu', manifest, root)


if __name__ == '__main__':
    unittest.main()
