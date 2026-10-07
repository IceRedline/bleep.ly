"""Real FFmpeg regression tests; no model downloads or network access."""
import array
import contextlib
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from censor.audio import prepare_sound, render_bed, render_beep
from censor.cli import main
from censor.ffmpeg import extract_audio, media_info, run
from censor.models import CensorRange, WordTimestamp

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="censor-test-")
        self.addCleanup(self.folder.cleanup)
        self.work = Path(self.folder.name)
        self.source = self.work / "видео & source.mov"
        self.sound = self.work / "beep.wav"
        self.transcript = self.work / "review.json"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=3",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264",
             "-c:a", "pcm_s16le", "-timecode", "01:00:00:00", str(self.source)])
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=0.9",
             "-c:a", "pcm_s16le", str(self.sound)])
        self.transcript.write_text(json.dumps({"words": [
            {"word": "ебать", "start": 1, "end": 1.3, "profane": True},
            {"word": "блядь", "start": 1.32, "end": 1.7, "profane": True}]}))

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / "censor.py"), str(self.source), "--censor-style", "full", *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def decode(self, path, start, duration):
        result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ss", str(start),
                                 "-t", str(duration), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                                 "-f", "f32le", "-"], check=True, capture_output=True)
        data = array.array("f")
        data.frombytes(result.stdout)
        return data

    def rms(self, data):
        return math.sqrt(sum(x*x for x in data) / len(data))

    def amplitude(self, data, frequency):
        return 2 * abs(sum(x * complex(math.cos(2*math.pi*frequency*i/48000),
                                      math.sin(2*math.pi*frequency*i/48000)) for i, x in enumerate(data))) / len(data)

    def test_video_stream_copy_and_beep_mixing(self):
        output = self.work / "output.mov"
        self.cli("--from-transcript", self.transcript, "--sound", self.sound, "--output", output)
        def video_hash(path):
            return run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c:v", "copy",
                        "-f", "hash", "-hash", "sha256", "-"])
        self.assertEqual(video_hash(self.source), video_hash(output))
        self.assertAlmostEqual(media_info(output).duration, 3, places=2)
        censored = self.decode(output, 1.05, .6)
        self.assertLess(self.amplitude(censored, 440), .002)
        self.assertGreater(self.amplitude(censored, 1000), .05)
        clean = self.decode(output, .2, .4)
        self.assertGreater(self.amplitude(clean, 440), .1)
        self.assertLess(self.amplitude(clean, 1000), .001)

    def test_fcpxml_assets_and_mute_duck_envelopes(self):
        xml = self.work / "edit.fcpxml"
        self.cli("--from-transcript", self.transcript, "--sound", self.sound, "--fcpxml", xml)
        self.assertFalse(self.source.with_name(self.source.stem + "_censored.mov").exists())
        root = ET.parse(xml).getroot()
        clips = root.findall(".//spine/asset-clip/asset-clip")
        self.assertEqual(len(clips), 2)  # bed plus ONE merged beep
        bed = self.work / "edit_media/original_censored.wav"
        self.assertEqual(self.rms(self.decode(bed, 1.05, .6)), 0)
        self.assertGreater(self.rms(self.decode(bed, .2, .4)), .08)
        beep = self.work / "edit_media/beep_0001.wav"
        self.assertEqual(len(self.decode(beep, 0, 2)), round(.9 * 48000))
        info = media_info(self.source)
        duck = self.work / "duck.wav"
        render_bed(self.source, duck, info, [CensorRange(1, 1.7)], "duck", -30, self.work)
        self.assertAlmostEqual(self.rms(self.decode(duck, 1.05, .4)) / self.rms(self.decode(duck, .2, .4)),
                               10 ** (-30/20), places=4)
        # Every gain transition is sample-based; no frame-quantized discontinuity.
        edge = self.decode(bed, .94, .02)
        self.assertLess(max(abs(a-b) for a, b in zip(edge, edge[1:])), .009)

    def test_dry_run_manual_flags_and_no_profanity(self):
        before = set(self.work.rglob("*"))
        stdout = self.cli("--from-transcript", self.transcript, "--dry-run")
        self.assertIn("Found 2", stdout)
        self.assertEqual(before, set(self.work.rglob("*")))
        data = json.loads(self.transcript.read_text())
        for word in data["words"]:
            word["profane"] = False
        self.transcript.write_text(json.dumps(data))
        stdout = self.cli("--from-transcript", self.transcript, "--sound", self.sound)
        self.assertIn("No profanity detected.", stdout)
        self.assertEqual(before, set(self.work.rglob("*")))

    def test_inference_cache_and_dry_run_no_writes(self):
        args = [str(self.source), "--dry-run"]
        with patch("censor.cli.FasterWhisperBackend.transcribe", return_value=[WordTimestamp("бля", 1, 1.3)]) as backend:
            before = set(self.work.rglob("*"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            self.assertEqual(before, set(self.work.rglob("*")))
            backend.assert_called_once()
            backend.reset_mock()
            normal = [str(self.source), "--sound", str(self.sound)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(normal), 0)
            backend.assert_called_once()
            backend.reset_mock()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            backend.assert_not_called()
        self.assertTrue(self.source.with_suffix(".transcript.json").exists())

    def test_existing_output_and_invalid_flags(self):
        output = self.work / "keep.mov"
        output.write_bytes(b"keep")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            result = main([str(self.source), "--from-transcript", str(self.transcript), "--sound", str(self.sound), "--output", str(output)])
        self.assertEqual(result, 1)
        self.assertEqual(output.read_bytes(), b"keep")

    def test_mlx_cli_cache_is_separate_and_reused(self):
        with patch("censor.cli.MLXWhisperBackend.transcribe", return_value=[WordTimestamp("бля", 1, 1.3)]) as gpu, \
             patch("censor.cli.FasterWhisperBackend.transcribe", return_value=[WordTimestamp("бля", 1, 1.3)]) as cpu, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.source), "--backend", "mlx", "--transcribe-only"]), 0)
            self.assertEqual(main([str(self.source), "--backend", "mlx", "--dry-run"]), 0)
            gpu.assert_called_once()
            cpu.assert_not_called()
            self.assertEqual(main([str(self.source), "--dry-run"]), 0)
            cpu.assert_called_once()
        data = json.loads(self.source.with_suffix(".transcript.json").read_text())
        self.assertEqual(data["metadata"]["backend"], "mlx")
        self.assertEqual(data["metadata"]["compute_type"], "float16")

    def test_transcribe_only_saves_review_without_sound(self):
        with patch("censor.cli.FasterWhisperBackend.transcribe", return_value=[WordTimestamp("бля", 1, 1.3)]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(self.source), "--transcribe-only"]), 0)
        data = json.loads(self.source.with_suffix(".transcript.json").read_text())
        self.assertTrue(data["words"][0]["profane"])
        self.assertFalse(self.source.with_name(self.source.stem + "_censored.mov").exists())

    def test_missing_audio_and_multiple_streams(self):
        from censor.utils import CensorError
        silent = self.work / "silent.mov"
        run(["ffmpeg", "-v", "error", "-i", str(self.source), "-map", "0:v:0", "-c", "copy", str(silent)])
        with self.assertRaisesRegex(CensorError, "no audio"):
            media_info(silent)
        multi = self.work / "multi.mov"
        run(["ffmpeg", "-v", "error", "-i", str(self.source), "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:0", "-c", "copy", str(multi)])
        with self.assertRaisesRegex(CensorError, "Select --audio-stream"):
            media_info(multi)
        self.assertEqual(media_info(multi, 1).audio_index, 2)

    def test_nonzero_start_time_normalization(self):
        shifted = self.work / "shifted.mov"
        run(["ffmpeg", "-v", "error", "-itsoffset", "10", "-i", str(self.source), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", str(shifted)])
        info = media_info(shifted)
        self.assertAlmostEqual(info.start, 10)
        speech = self.work / "shifted.wav"
        extract_audio(shifted, speech, info)
        self.assertGreater(self.rms(self.decode(speech, .1, .2)), .05)

    def test_sound_export_preserves_entire_cue(self):
        sound = self.work / "normalized.wav"
        prepare_sound(self.sound, sound, .9)
        beep = self.work / "short.wav"
        render_beep(sound, beep)
        data = self.decode(beep, 0, 1)
        self.assertEqual(len(data), 43200)
        self.assertAlmostEqual(data[0], 0, places=6)

    def test_two_speaker_cues_preserve_full_tails_and_mute_timing(self):
        other = self.work / 'other.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=2000:sample_rate=48000:duration=0.5',
             '-c:a', 'pcm_s16le', str(other)])
        self.transcript.write_text(json.dumps({'words': [
            dict(word='бля', start=1, end=1.2, profane=True, speaker='me'),
            dict(word='бля', start=2, end=2.2, profane=True, speaker='others')]}))
        output = self.work / 'two.mov'
        xml = self.work / 'two.fcpxml'
        self.cli('--from-transcript', self.transcript, '--sound', self.sound, '--sound-others', other,
                 '--padding-before', '0', '--padding-after', '0', '--output', output, '--fcpxml', xml)
        mine = self.decode(output, 1.04, .1)
        theirs = self.decode(output, 2.04, .1)
        self.assertGreater(self.amplitude(mine, 1000), .05)
        self.assertLess(self.amplitude(mine, 2000), .005)
        self.assertGreater(self.amplitude(theirs, 2000), .05)
        self.assertLess(self.amplitude(theirs, 1000), .005)
        tail = self.decode(output, 2.3, .1)
        self.assertGreater(self.amplitude(tail, 440), .1)
        self.assertGreater(self.amplitude(tail, 2000), .05)
        clips = ET.parse(xml).getroot().findall('.//spine/asset-clip/asset-clip')[1:]
        self.assertEqual([clip.get('duration') for clip in clips], ['9/10s', '1/2s'])
        self.assertEqual(len(self.decode(self.work / 'two_media/beep_0002.wav', 0, 1)), 24000)

    def test_sound_plays_once_at_original_speed(self):
        cue = self.work / "two-tone.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=0.2",
             "-f", "lavfi", "-i", "sine=frequency=2000:sample_rate=48000:duration=0.2",
             "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]", "-map", "[out]", str(cue)])
        result = self.work / "once.wav"
        render_beep(cue, result)
        self.assertEqual(len(self.decode(result, 0, 2)), 19200)
        opening = self.decode(result, .1, .1)
        latter = self.decode(result, .25, .1)
        self.assertGreater(self.amplitude(opening, 1000), .09)
        self.assertLess(self.amplitude(latter, 1000), .005)
        self.assertGreater(self.amplitude(latter, 2000), .09)
        self.assertEqual(len(self.decode(result, .45, .1)), 0)

    def test_middle_mode_preserves_start_and_end_of_word(self):
        output = self.work / "middle.mov"
        self.cli("--censor-style", "middle", "--from-transcript", self.transcript,
                 "--sound", self.sound, "--output", output)
        # First word [1, 1.3]: cover [1.06, 1.24], leaving both edges audible.
        for start in (1.005, 1.255):
            self.assertGreater(self.amplitude(self.decode(output, start, .025), 440), .08)
        center = self.decode(output, 1.1, .05)
        self.assertLess(self.amplitude(center, 440), .002)
        self.assertGreater(self.amplitude(center, 1000), .09)
        # Once mute ends at 1.24, speech resumes while the full cue continues.
        tail = self.decode(output, 1.26, .05)
        self.assertGreater(self.amplitude(tail, 440), .09)
        self.assertGreater(self.amplitude(tail, 1000), .09)

    def test_delayed_audio_keeps_video_timeline(self):
        delayed = self.work / "delayed.mov"
        run(["ffmpeg", "-v", "error", "-i", str(self.source), "-itsoffset", "0.5", "-i", str(self.sound),
             "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(delayed)])
        speech = self.work / "speech.wav"
        info = media_info(delayed)
        extract_audio(delayed, speech, info)
        self.assertEqual(self.rms(self.decode(speech, 0, .4)), 0)
        self.assertGreater(self.rms(self.decode(speech, .51, .05)), .05)
