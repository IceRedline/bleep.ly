"""Exercise the benchmark request/resume contract without running inference."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class GPUBenchmarkTests(unittest.TestCase):
    def test_language_reaches_worker_and_resume_checks_language_and_source_content(self):
        spec = importlib.util.spec_from_file_location('gpu_benchmark', Path(__file__).resolve().parents[1] / 'scripts/benchmark-gpu-models.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.mp4'
            source.write_bytes(b'original')
            output = Path(folder) / 'results'
            requests = []

            def worker(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text())
                requests.append(request)
                kwargs['stdout'].write(json.dumps(dict(event='result', cache_hit=False,
                    words=[dict(word='fuck', profane=True)], analysis_seconds=1, duration=677)) + '\n')
                return SimpleNamespace(returncode=0)

            argv = ['benchmark', str(source), '--output', str(output), '--language', 'en', '--models', 'large-v3']
            with patch.dict(os.environ), patch.object(runner.subprocess, 'run', side_effect=worker), patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
                runner.main()
                runner.main()
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]['language'], 'en')
                self.assertTrue(requests[0]['bypass_cache'])
                result = json.loads((output / 'large-v3.result.json').read_text())
                self.assertEqual(result['language'], 'en')
                self.assertEqual(len(result['source_sha256']), 64)
                with patch('sys.argv', [value if value != 'en' else 'ru' for value in argv]):
                    with self.assertRaisesRegex(ValueError, 'another source or language'):
                        runner.main()
                source.write_bytes(b'changed at the same path')
                with self.assertRaisesRegex(ValueError, 'another source or language'):
                    runner.main()

    def test_gigaam_english_is_rejected_before_download_or_inference(self):
        spec = importlib.util.spec_from_file_location('gpu_benchmark', Path(__file__).resolve().parents[1] / 'scripts/benchmark-gpu-models.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch('sys.argv', ['benchmark', 'missing.mp4', '--output', 'unused', '--language', 'en', '--models', 'gigaam-v3']), contextlib.redirect_stderr(io.StringIO()), patch.object(runner, 'prepare') as prepare:
            with self.assertRaises(SystemExit) as error:
                runner.main()
            self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()
