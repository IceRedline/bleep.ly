"""Incremental previews match the export mixer without rendering unchanged audio."""
import array
import contextlib
import copy
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from censor.desktop import export, fingerprint
from censor.ffmpeg import run
from censor.preview import preview
from censor.utils import CensorError


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "source.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
             "-af", "volume=9", str(self.source)])
        self.document = dict(source=str(self.source), fingerprint=fingerprint(self.source), duration=8,
                             tracks=[dict(index=0)], words=[
                                 dict(word="word", start=start, end=end, mute_start=start,
                                      mute_end=end, profane=True, audio_track=0)
                                 for start, end in [(.7, .9), (.85, 1.05), (1.1, 1.3), (4.3, 4.5), (5, 5.2)]])
        self.serial = 0

    def render(self, document=None, previous=None, **options):
        self.serial += 1
        request = dict(document=document or self.document, output=str(self.folder / f"preview-{self.serial}.wav"),
                       preview_cache=str(self.folder / "cache"), sound="beep")
        request.update(options)
        if previous:
            request["previous_output"] = previous["output"]
        with contextlib.redirect_stdout(io.StringIO()):
            result = preview(request)
        return request, result

    def assert_matches_export(self, request):
        self.serial += 1
        reference = self.folder / f"export-{self.serial}.wav"
        with contextlib.redirect_stdout(io.StringIO()):
            export({**request, "format": "audio", "output": str(reference)})
        def pcm(path):
            data = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-"])
            return array.array("f", data)
        actual, expected = pcm(request["output"]), pcm(reference)
        self.assertEqual(len(actual), len(expected))
        self.assertLess(max(abs(a - b) for a, b in zip(actual, expected)), 3e-6)

    def test_edits_restore_speech_preserve_cue_tails_and_match_export(self):
        cue = self.folder / "cue.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1200:duration=1.2",
             "-af", "volume=5", str(cue)])
        request, initial = self.render(sound="custom", custom_sound=str(cue))
        self.assertTrue(initial["source_decoded"])
        self.assert_matches_export(request)
        original_bytes = Path(initial["output"]).read_bytes()
        edited = copy.deepcopy(self.document)
        edited["words"][0]["profane"] = False  # Changes the beginning of a merged interval.
        request, changed = self.render(edited, initial, sound="custom", custom_sound=str(cue))
        self.assertFalse(changed["source_decoded"])
        self.assertLess(changed["rendered_seconds"], 3)
        self.assertEqual(changed["patches"], 1)
        self.assert_matches_export(request)
        self.assertEqual(Path(initial["output"]).read_bytes(), original_bytes)
        # Move an interval, including restoring its old location and a cue tail
        # that starts before the patch's render window.
        edited["words"][2].update(mute_start=2.1, mute_end=2.3)
        request, moved = self.render(edited, changed, sound="custom", custom_sound=str(cue))
        self.assert_matches_export(request)
        edited["words"][-1]["profane"] = False
        request, tail = self.render(edited, moved, sound="custom", custom_sound=str(cue))
        self.assert_matches_export(request)
        request, undone = self.render(self.document, tail, sound="custom", custom_sound=str(cue))
        self.assert_matches_export(request)

    def test_silence_beep_zero_intervals_and_boundary_edits(self):
        for mode in ["silence", "beep"]:
            with self.subTest(mode=mode):
                request, initial = self.render(sound=mode)
                self.assert_matches_export(request)
                empty = copy.deepcopy(self.document)
                for word in empty["words"]:
                    word["profane"] = False
                request, cleared = self.render(empty, initial, sound=mode)
                self.assert_matches_export(request)
                empty["words"][0].update(profane=True, mute_start=0, mute_end=.15)
                empty["words"][1].update(profane=True, mute_start=7.8, mute_end=8)
                request, added = self.render(empty, cleared, sound=mode)
                self.assertFalse(added["source_decoded"])
                self.assert_matches_export(request)

    def test_cancellation_does_not_publish_or_modify_previous_preview(self):
        _, initial = self.render()
        before = Path(initial["output"]).read_bytes()
        edited = copy.deepcopy(self.document)
        edited["words"][2]["profane"] = False
        original_run = run
        def cancel_render(args, *rest):
            if "-filter_complex_script" in args:
                raise KeyboardInterrupt()
            return original_run(args, *rest)
        with patch("censor.preview.run", side_effect=cancel_render), self.assertRaises(KeyboardInterrupt):
            self.render(edited, initial)
        self.assertFalse((self.folder / f"preview-{self.serial}.wav").exists())
        self.assertEqual(Path(initial["output"]).read_bytes(), before)
        request, retried = self.render(edited, initial)
        self.assertFalse(retried["source_decoded"])
        self.assert_matches_export(request)

    def test_changed_source_rejected_and_changed_custom_sound_invalidates_previous(self):
        cue = self.folder / "cue.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1200:duration=0.8", str(cue)])
        _, initial = self.render(sound="custom", custom_sound=str(cue))
        cue.unlink()
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=2000:duration=0.3", str(cue)])
        request, _ = self.render(previous=initial, sound="custom", custom_sound=str(cue))
        self.assert_matches_export(request)
        with self.source.open("ab") as file:
            file.write(b"changed")
        with self.assertRaisesRegex(CensorError, "Source changed"):
            self.render(previous=initial)
