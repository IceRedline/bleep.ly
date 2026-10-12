import csv
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from censor.cache_policy import MAX_AGE, prune_recognition, reserve_preview, tree_size
from censor.utils import CensorError


class CachePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def file(self, path, size, age=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * size)
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_preview_evicts_old_snapshots_but_keeps_playing_audio_and_current_source(self):
        session = self.root / 'session'
        playing = self.file(session / str(uuid.uuid4()) / 'censored.wav', 200)
        old = self.file(session / str(uuid.uuid4()) / 'censored.wav', 400)
        source = self.file(session / 'audio' / ('a' * 64) / 'source.wav', 200)
        reserve_preview(session, {playing.parent, source.parent}, 100, limit=600)
        self.assertFalse(old.exists())
        self.assertTrue(playing.exists())
        self.assertTrue(source.exists())
        self.assertLessEqual(tree_size(session) + 100, 600)

    def test_preview_refuses_an_oversized_working_set_without_deleting_live_files(self):
        source = self.file(self.root / 'audio' / ('b' * 64) / 'source.wav', 500)
        with self.assertRaisesRegex(CensorError, 'temporary audio limit'):
            reserve_preview(self.root, {source.parent}, 200, limit=600)
        self.assertTrue(source.exists())

    def test_preview_keeps_at_most_eight_variants_even_below_byte_limit(self):
        variants = [self.file(self.root / str(uuid.uuid4()) / 'censored.wav', 10)
                    for _ in range(9)]
        playing = variants[0]
        reserve_preview(self.root, {playing.parent}, 0, limit=10000)
        self.assertTrue(playing.exists())
        self.assertEqual(sum(path.exists() for path in variants), 8)

    def test_77_minute_preview_fits_initial_render_and_edit_with_playback(self):
        from types import SimpleNamespace
        frames = 77 * 60 * 48000
        with patch('censor.cache_policy.shutil.disk_usage', return_value=SimpleNamespace(free=20 * 1024**3)):
            # First render: float32 source, PCM24 baseline, output and a full-length patch.
            reserve_preview(self.root, set(), frames * (8 + 6 + 6 + 6) + 65536)
            source = self.root / 'audio' / ('a' * 64)
            playing = self.root / str(uuid.uuid4())
            old = self.root / str(uuid.uuid4())
            for path, size in [(source / 'source.wav', frames * 8),
                               (source / 'limited.wav', frames * 6),
                               (playing / 'censored.wav', frames * 6),
                               (old / 'censored.wav', frames * 6)]:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Sparse fixtures account for realistic sizes without writing gigabytes.
                with path.open('wb') as handle:
                    handle.truncate(size)
            reserve_preview(self.root, {source, playing}, frames * 12 + 65536)
            self.assertFalse(old.exists())
            self.assertTrue((source / 'source.wav').exists())
            self.assertTrue((playing / 'censored.wav').exists())

    def test_preview_checks_free_disk_space(self):
        from types import SimpleNamespace
        with patch('censor.cache_policy.shutil.disk_usage', return_value=SimpleNamespace(free=100)):
            with self.assertRaisesRegex(CensorError, 'free disk space'):
                reserve_preview(self.root, set(), 200, limit=1000)

    def test_preview_does_not_follow_links_or_remove_unmanaged_folders(self):
        outside = self.file(self.root / 'recordings' / 'movie.mov', 100)
        session = self.root / 'session'
        session.mkdir()
        (session / str(uuid.uuid4())).symlink_to(outside.parent, target_is_directory=True)
        unmanaged = self.file(session / 'exports' / 'movie.mov', 100)
        with self.assertRaises(CensorError):
            reserve_preview(session, set(), 200, limit=100)
        self.assertTrue(outside.exists())
        self.assertTrue(unmanaged.exists())

    def test_recognition_removes_expired_transcripts_and_history_pairs(self):
        cache, history = self.root / 'cache', self.root / 'history'
        expired = self.file(cache / ('a' * 64 + '.json'), 100, MAX_AGE + 10)
        recent = self.file(cache / ('b' * 64 + '.json'), 100)
        old_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
        for run_id, age in [(old_id, MAX_AGE + 10), (new_id, 0)]:
            record = history / 'runs' / f'{run_id}.json'
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps({'summary': {'run_id': run_id, 'snapshot': f'runs/{run_id}.json'}}))
            self.file(record.with_suffix('.csv'), 100)
            os.utime(record, (time.time() - age, time.time() - age))
        prune_recognition(cache, history, limit=10000)
        self.assertFalse(expired.exists())
        self.assertTrue(recent.exists())
        self.assertFalse((history / 'runs' / f'{old_id}.json').exists())
        self.assertFalse((history / 'runs' / f'{old_id}.csv').exists())
        with (history / 'runs.csv').open(encoding='utf-8-sig') as handle:
            self.assertEqual([r['run_id'] for r in csv.DictReader(handle)], [new_id])

    def test_recognition_bounds_total_size_without_touching_models_reviews_or_sources(self):
        cache, history = self.root / 'cache', self.root / 'history'
        old = self.file(cache / ('a' * 64 + '.json'), 600, 10)
        new = self.file(cache / ('b' * 64 + '.json'), 600)
        model = self.file(cache / 'models' / 'weights.bin', 2000)
        review = self.file(cache / 'last-review.json', 2000)
        source = self.file(self.root / 'source.mov', 2000)
        (cache / ('c' * 64 + '.json')).symlink_to(source)
        prune_recognition(cache, history, limit=1300)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        for path in [model, review, source]:
            self.assertEqual(path.stat().st_size, 2000)

    def test_history_deletion_uses_owned_filenames_not_metadata_paths(self):
        outside = self.file(self.root / 'source.mov', 100)
        cache, history = self.root / 'cache', self.root / 'history'
        record = history / 'runs' / f'{uuid.uuid4()}.json'
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'summary': {'words_csv': str(outside), 'snapshot': str(outside)}}))
        os.utime(record, (0, 0))
        prune_recognition(cache, history)
        self.assertTrue(outside.exists())

    def test_protected_paths_work_through_macos_style_directory_aliases(self):
        storage = self.root / 'private'
        source = self.file(storage / 'session' / str(uuid.uuid4()) / 'censored.wav', 500)
        alias = self.root / 'var'
        alias.symlink_to(storage, target_is_directory=True)
        with self.assertRaises(CensorError):
            reserve_preview(alias / 'session', {source.parent}, 500, limit=600)
        self.assertTrue(source.exists())

    def test_orphan_history_csv_and_incomplete_writes_are_bounded(self):
        cache, history = self.root / 'cache', self.root / 'history'
        orphan = self.file(history / 'runs' / f'{uuid.uuid4()}.csv', 2000, MAX_AGE + 1)
        interrupted = self.file(cache / ('.' + 'a' * 64 + '.json.abcdefgh'), 2000, MAX_AGE + 1)
        prune_recognition(cache, history, limit=1000)
        self.assertFalse(orphan.exists())
        self.assertFalse(interrupted.exists())
