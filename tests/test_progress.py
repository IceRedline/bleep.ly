import hashlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from censor.ffmpeg import run
from censor.progress import Progress
from censor.transcription import file_hash
from censor.utils import CensorError


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ProgressTests(unittest.TestCase):
    def test_narrow_terminal_does_not_wrap(self):
        stream = Terminal()
        with patch("censor.progress.get_terminal_size", return_value=os.terminal_size((60, 24))):
            with Progress("Transcribing", 1200, stream=stream):
                pass
        self.assertTrue(all(len(line.rstrip('\n')) < 60 for line in stream.getvalue().split('\r')))
        self.assertIn("100%", stream.getvalue())

    def test_eta_uses_elapsed_time_and_completed_work(self):
        stream = io.StringIO()
        clock = [0.0]
        with patch("censor.progress.time.monotonic", side_effect=lambda: clock[0]):
            with Progress("Transcribing", 1200, stream=stream) as bar:
                clock[0] = 60
                bar.update(300)
                self.assertIn("25%", stream.getvalue())
                self.assertIn("05:00/20:00", stream.getvalue())
                self.assertIn("ETA ~03:00", stream.getvalue())

    def test_terminal_rewrites_and_finishes_only_on_success(self):
        stream = Terminal()
        with Progress("Transcribing", 1200, stream=stream) as bar:
            bar.update(600)
            bar.update(1200)
            self.assertNotIn("100%", stream.getvalue())
        self.assertIn("\r", stream.getvalue())
        self.assertIn("100%", stream.getvalue())
        self.assertIn("20:00/20:00", stream.getvalue())
        self.assertTrue(stream.getvalue().endswith("\n"))

    def test_progress_never_moves_backward_and_ignores_invalid_values(self):
        stream = io.StringIO()
        with Progress("Render", 100, stream=stream) as bar:
            bar.update(50)
            bar.update(10)
            bar.update(float("nan"))
            self.assertEqual(bar.current, 50)
            bar.update(1000)
            self.assertEqual(bar.current, 100)
            self.assertIn("99%", stream.getvalue())
        self.assertNotIn("\r", stream.getvalue())

    def test_error_does_not_show_success(self):
        stream = Terminal()
        with self.assertRaises(ValueError):
            with Progress("Render", 20, stream=stream) as bar:
                bar.update(20)
                raise ValueError("fail")
        self.assertNotIn("100%", stream.getvalue())
        self.assertIn("stopped", stream.getvalue())
        self.assertTrue(stream.getvalue().endswith("\n"))

    def test_hash_reports_bytes_without_changing_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input"
            data = b"x" * (4 * 1024 * 1024 + 19)
            path.write_bytes(data)
            seen = []
            self.assertEqual(file_hash(path, seen.append), hashlib.sha256(data).hexdigest())
            self.assertEqual(seen, [4 * 1024 * 1024, len(data)])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_ffmpeg_reports_time_and_keeps_audio_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("normal.wav", "progress.wav")]
            base = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "pcm_s16le"]
            run([*base, str(paths[0])])
            seen = []
            run([*base, str(paths[1])], seen.append)
            self.assertTrue(seen)
            self.assertAlmostEqual(seen[-1], 1, places=2)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_ffmpeg_failure_remains_actionable(self):
        with self.assertRaisesRegex(CensorError, "failed"):
            run(["ffmpeg", "-v", "error", "-nostdin", "-i", "/missing/не существует.mov", "-f", "null", "-"], lambda _: None)
