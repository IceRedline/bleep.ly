import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from censor.cli import select_backend
from censor.utils import CensorError


class Terminal(io.StringIO):
    def isatty(self):
        return True


class BackendMenuTests(unittest.TestCase):
    def test_interactive_retry_and_cpu_default(self):
        with patch("sys.stdin", Terminal()), contextlib.redirect_stdout(Terminal()) as output:
            with patch("builtins.input", side_effect=["bad", " 1 "]) as read:
                self.assertEqual(select_backend(None, None), "mlx")
                self.assertEqual(read.call_count, 2)
            for answer in ["2", ""]:
                with patch("builtins.input", return_value=answer):
                    self.assertEqual(select_backend(None, None), "faster-whisper")
        self.assertIn("Введите 1 или 2", output.getvalue())

    def test_explicit_backend_and_transcript_never_prompt(self):
        with patch("sys.stdin", Terminal()), contextlib.redirect_stdout(Terminal()), patch("builtins.input") as read:
            self.assertEqual(select_backend("mlx", None), "mlx")
            self.assertEqual(select_backend("faster-whisper", None), "faster-whisper")
            self.assertEqual(select_backend(None, Path("review.json")), "faster-whisper")
            read.assert_not_called()

    def test_redirected_input_or_output_never_blocks(self):
        for stdin, stdout in [(io.StringIO(), Terminal()), (Terminal(), io.StringIO())]:
            with patch("sys.stdin", stdin), contextlib.redirect_stdout(stdout), patch("builtins.input") as read:
                self.assertEqual(select_backend(None, None), "faster-whisper")
                read.assert_not_called()
                self.assertEqual(stdout.getvalue(), "")

    def test_eof_cancels_without_starting_inference(self):
        with patch("sys.stdin", Terminal()), contextlib.redirect_stdout(Terminal()), \
             patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesRegex(CensorError, "Выбор отменён"):
                select_backend(None, None)
