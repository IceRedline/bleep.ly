import csv
import json
import tempfile
import unittest
from pathlib import Path

from censor.recognition_history import import_cache, record_run


class RecognitionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "history"
        self.cache = self.root / "cache.json"
        self.metadata = dict(backend="mlx", model="test-model", source_sha256="source", audio_index=0)
        self.words = [dict(word="блядь,", start=1, end=1.3, profane=False)]
        self.save_cache()

    def save_cache(self):
        self.cache.write_text(json.dumps(dict(metadata=self.metadata, words=self.words)))

    def rows(self):
        with (self.output / "runs.csv").open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_explicit_cpu_device_overrides_gpu_backend_name(self):
        for backend in ['parakeet-mlx', 'mlx-qwen3-asr', 'gigaam-mps']:
            record_run(self.output, metadata={**self.metadata, 'backend': backend, 'device': 'CPU'},
                       words=self.words, cache_path=self.cache)
        self.assertEqual({row['device'] for row in self.rows()}, {'CPU'})

    def test_import_is_idempotent_but_preserves_changed_cache(self):
        first = import_cache(self.output, self.cache)
        self.assertEqual(first, import_cache(self.output, self.cache))
        self.words.append(dict(word="привет", start=2, end=2.3, profane=False))
        self.save_cache()
        second = import_cache(self.output, self.cache)
        self.assertNotEqual(first, second)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(int(row["total_words"]) for row in rows), [1, 2])
        for row in rows:
            self.assertEqual(row["explicit_words"], "1")
            self.assertEqual(row["analysis_seconds"], "")
            self.assertEqual(row["timestamp_utc"], "")
            self.assertEqual(row["cache_hit"], "")
            self.assertEqual(row["record_kind"], "cache_import")
        self.assertFalse(json.loads(self.cache.read_text())["words"][0]["profane"])

    def test_every_run_is_retained_with_full_metadata_and_safe_csv(self):
        self.words[0]["profane"] = True
        self.metadata["native_metrics"] = {"nested": "retained"}
        self.words.append(dict(word="=SUM(1,2)", start=2, end=3, profane=False))
        for cache_hit in (False, True, False):
            record_run(self.output, metadata=self.metadata, words=self.words,
                       cache_path=self.cache, source="=danger.wav", cache_hit=cache_hit,
                       recognition_seconds=None if cache_hit else 10)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["run_id"] for row in rows}), 3)
        self.assertEqual(sorted(row["recognition_seconds"] for row in rows), ["", "10", "10"])
        for row in rows:
            snapshot = json.loads((self.output / row["snapshot"]).read_text())
            self.assertEqual(snapshot["metadata"], self.metadata)
            self.assertEqual(snapshot["words"], self.words)
            self.assertEqual(row["source"], "'=danger.wav")
            self.assertIn("'=SUM", (self.output / row["words_csv"]).read_text())

    def test_next_write_recovers_csv_from_snapshots(self):
        import_cache(self.output, self.cache)
        row = self.rows()[0]
        (self.output / "runs.csv").write_text("interrupted")
        (self.output / row["words_csv"]).unlink()
        import_cache(self.output, self.cache)
        self.assertEqual(self.rows(), [row])
        self.assertTrue((self.output / row["words_csv"]).is_file())
