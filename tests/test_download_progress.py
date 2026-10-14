import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from censor.download_progress import byte_progress_bar
from censor.experimental_gpu import prepare, prepare_hub_asset


class ModelDownloadProgressTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('censor.download_progress.time.monotonic', side_effect=iter(range(10000)))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_byte_counts_ignore_transfer_and_file_bars_and_never_complete_early(self):
        events = []
        bar_type = byte_progress_bar('Downloading model', lambda *e: events.append(e), total=100)
        with bar_type(total=50, initial=20, unit='B', desc='Reconstructing') as bar:
            bar.update(30)
            bar.total = 100  # Hub discovers the next file after the first connects.
            bar.refresh()
            bar.update(50)
        self.assertIn(.5, [value for _, value in events])
        self.assertEqual(events[-1][1], .99)
        before = list(events)
        with bar_type(total=100, unit='B', desc='Downloading bytes', name='hub.transfer') as transfer:
            transfer.update(100)
        with bar_type(total=10, desc='Fetching 10 files') as files:
            files.update(10)
        self.assertEqual(events, before)
        self.assertTrue(all(value < 1 for _, value in events))

    def test_unknown_length_stays_indeterminate_and_retry_does_not_double_count(self):
        events = []
        bar_type = byte_progress_bar('Downloading GigaAM', lambda *e: events.append(e))
        with bar_type(unit='iB') as unknown:
            unknown.update(100)
        self.assertEqual(events[-1][1], 0)
        self.assertNotIn(' / ', events[-1][0])
        with bar_type(total=100, unit='iB') as first:
            first.update(60)
        self.assertEqual(events[-1][1], .6)
        with bar_type(total=100, unit='iB') as retry:
            retry.update(20)
        self.assertEqual(events[-1][1], .2)

    def test_hub_reports_network_bytes_despite_large_disk_flushes_and_only_finishes_on_success(self):
        for failure in [False, True]:
            events = []
            def download(repo, **kwargs):
                self.assertEqual(kwargs['revision'], 'pinned')
                if kwargs.get('local_files_only'):
                    return '/partial/snapshot'  # A directory is not proof of completeness.
                self.assertNotIn('dry_run', kwargs)
                bar_type = kwargs['tqdm_class']
                with bar_type(total=1_000_000_000, unit='B', desc='Downloading bytes', name='hub.transfer') as transfer, \
                        bar_type(total=1_000_000_000, initial=500_000_000, unit='B', desc='Reconstructing') as disk:
                    transfer.update(10_000_000)
                    self.assertEqual(events[-1], ('Downloading Qwen — 10.0 MB downloaded', 0))
                    before = list(events)
                    disk.update(400_000_000)  # Includes cached/resumed bytes and a buffered flush.
                    self.assertEqual(events, before)
                    transfer.update(20_000_000)
                    if failure:
                        raise OSError('connection lost')
                    transfer.total = transfer.n  # Hub finalizes its synthetic terminal-bar total.
                    transfer.refresh()
                return '/cached/model'
            with patch('huggingface_hub.snapshot_download', side_effect=download):
                if failure:
                    with self.assertRaisesRegex(OSError, 'connection lost'):
                        prepare_hub_asset('repo', 'pinned', 'Qwen', False, lambda *e: events.append(e))
                else:
                    self.assertEqual(prepare_hub_asset('repo', 'pinned', 'Qwen', False, lambda *e: events.append(e)), '/cached/model')
            self.assertIn(('Downloading Qwen — 30.0 MB downloaded', 0), events)
            self.assertTrue(all(value == 0 and ' / ' not in label for label, value in events if label.startswith('Downloading ')))
            self.assertEqual(any(value == 1 for _, value in events), not failure)
            if not failure:
                self.assertEqual(events[-1], ('Qwen model ready', 1))

    def test_network_counter_flushes_last_bytes_once_and_cannot_complete_on_close(self):
        events = []
        with patch('censor.download_progress.time.monotonic', return_value=10):
            bar_type = byte_progress_bar('Downloading Qwen', lambda *e: events.append(e), network_only=True)
            bar = bar_type(total=100_000_000, unit='B', name='hub.transfer')
            bar.update(5_000_000)  # Throttled; close must still report these bytes.
            bar.close()
            self.assertEqual(events[-1], ('Downloading Qwen — 5.0 MB downloaded', 0))
            before = list(events)
            bar.close()
            self.assertEqual(events, before, 'Destructor must not emit progress after the result event')

    def test_hub_finalization_blocks_delayed_callbacks_and_destructors(self):
        events = []
        with patch('censor.download_progress.time.monotonic', return_value=10):
            bar_type = byte_progress_bar('Downloading Qwen', lambda *e: events.append(e), network_only=True)
            bar = bar_type(total=100_000_000, unit='B', name='hub.transfer')
            bar.update(8_000_000)
            bar_type.finish()
            self.assertEqual(events[-1], ('Downloading Qwen — 8.0 MB downloaded', 0))
            before = list(events)
            bar.update(1_000_000)
            bar.refresh()
            bar.close()
            bar_type.finish()
            self.assertEqual(events, before)

    def test_gigaam_reports_both_files_and_restores_downloader_on_failure(self):
        from tqdm import tqdm
        for failure in [False, True]:
            events = []
            module = SimpleNamespace(tqdm=tqdm)
            def download(repo, folder, suffix):
                with module.tqdm(total=100, unit='iB') as bar:
                    bar.update(40)
                    if failure:
                        raise OSError('offline')
                    bar.update(60)
                target = Path(folder)/f'{repo}{suffix}'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'cached')
            module._download_model = lambda repo, folder: download(repo, folder, '.ckpt')
            module._download_tokenizer = lambda repo, folder: download(repo, folder, '_tokenizer.model')
            with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'BLEEP_MODEL_CACHE': folder}), \
                    patch.dict('sys.modules', {'gigaam': module}), \
                    patch('censor.experimental_gpu.prepare_hub_asset', return_value='/cached/aligner'):
                if failure:
                    with self.assertRaisesRegex(OSError, 'offline'):
                        prepare('gigaam-v3', offline=False, progress=lambda *e: events.append(e))
                else:
                    self.assertEqual(prepare('gigaam-v3', offline=False, progress=lambda *e: events.append(e)),
                                     [str(Path(folder)/'gigaam'), '/cached/aligner'])
                    self.assertTrue(any(label.startswith('Downloading GigaAM tokenizer') and value > 0 for label, value in events))
            self.assertIs(module.tqdm, tqdm)
            self.assertTrue(any(label.startswith('Downloading GigaAM — ') and value == .4 for label, value in events))
