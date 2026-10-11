import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huggingface_hub.errors import LocalEntryNotFoundError
from censor import desktop
from censor.model_downloads import ModelDownloadRequired, requires_model_download
from censor.utils import CensorError


class ModelDownloadTests(unittest.TestCase):
    def test_wrapped_missing_model_is_distinct_from_inference_or_network_failure(self):
        missing = LocalEntryNotFoundError('No cached snapshot')
        wrapped = CensorError('Whisper transcription failed')
        wrapped.__cause__ = missing
        for error in (missing, wrapped, ModelDownloadRequired('Missing native model')):
            self.assertTrue(requires_model_download(error))
        for error in (RuntimeError('out of memory'), ConnectionError('server unreachable'),
                      FileNotFoundError('missing audio.wav')):
            self.assertFalse(requires_model_download(error))
        wrapped.__cause__ = wrapped
        self.assertFalse(requires_model_download(wrapped))

    def test_protocol_requests_consent_only_for_offline_analysis(self):
        for operation, offline, expected in [('analyze', True, 'model_download_required'),
                                              ('analyze', False, None), ('export', True, None)]:
            with self.subTest(operation=operation, offline=offline), tempfile.TemporaryDirectory() as folder:
                request = Path(folder) / 'request.json'
                request.write_text(json.dumps(dict(operation=operation, offline=offline)))
                missing = CensorError('Backend failure')
                missing.__cause__ = LocalEntryNotFoundError('No cached snapshot')
                output = io.StringIO()
                original_emit = desktop.emit
                try:
                    with (patch('sys.argv', ['desktop', str(request)]),
                          patch('censor.desktop.os.setsid'), patch('censor.desktop.signal.signal'),
                          patch('censor.desktop.require_tools'),
                          patch('censor.desktop.analyze', side_effect=missing),
                          patch('censor.desktop.export', side_effect=missing),
                          contextlib.redirect_stdout(output)):
                        self.assertEqual(desktop.main(), 1)
                finally:
                    desktop.emit = original_emit
                event = json.loads(output.getvalue())
                self.assertEqual(event.get('code'), expected)
                if expected:
                    self.assertIn('Settings', event['message'])
                    self.assertNotIn('local_files_only', event['message'])
