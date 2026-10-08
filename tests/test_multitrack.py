"""Real two-track renders: independent edits, full cue tails and stream copy."""
import array
import contextlib
import hashlib
import io
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from censor.desktop import analyze, export
from censor.ffmpeg import run, probe
from censor.models import WordTimestamp
from censor.utils import CensorError


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class MultiTrackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.work = Path(self.folder.name)
        self.source = self.work / 'two.mkv'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=25:d=4',
             '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
             '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=4',
             '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-c:a', 'pcm_s16le',
             '-metadata:s:a:0', 'title=Microphone', '-metadata:s:a:1', 'title=Guest', str(self.source)])
        self.request = dict(source=str(self.source), cache_dir=str(self.work / 'cache'), censor_style='full')
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        with patch('censor.desktop.FasterWhisperBackend.transcribe', side_effect=[
                [WordTimestamp('бля', 1, 1.3)], [WordTimestamp('бля', 2, 2.3)]]) as engine:
            self.document = analyze(self.request)
        self.assertEqual(engine.call_count, 2)

    def amplitude(self, path, track, start, frequency):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', f'0:a:{track}',
                                 '-ss', str(start), '-t', '0.05', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'],
                                capture_output=True, check=True)
        samples = array.array('f', result.stdout)
        return 2 * abs(sum(x * complex(math.cos(2*math.pi*frequency*i/48000),
                                      math.sin(2*math.pi*frequency*i/48000))
                           for i, x in enumerate(samples))) / len(samples)

    def video_hash(self, path):
        return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v',
                                        '-c', 'copy', '-f', 'hash', '-'])

    def render(self, name, **kwargs):
        output = self.work / name
        export(dict(document=self.document, output=str(output), format='video', sound='silence', **kwargs))
        return output

    def test_independent_censoring_preserves_two_tracks_and_video(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        output = self.render('result.mkv')
        audio = [s for s in probe(output)['streams'] if s['codec_type'] == 'audio']
        self.assertEqual([s['tags']['title'] for s in audio], ['Microphone', 'Guest'])
        self.assertEqual(self.video_hash(output), self.video_hash(self.source))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), before)
        for track, frequency, muted, intact in [(0, 440, 1.1, 2.1), (1, 880, 2.1, 1.1)]:
            self.assertLess(self.amplitude(output, track, muted, frequency), .005)
            self.assertGreater(self.amplitude(output, track, intact, frequency), .08)

    def test_track_caches_are_independent_and_scoped_import_is_required(self):
        with patch('censor.desktop.FasterWhisperBackend.transcribe') as engine:
            cached = analyze(self.request)
            selected = analyze({**self.request, 'audio_stream': 1})
        engine.assert_not_called()
        self.assertTrue(cached['cache_hit'])
        self.assertEqual([w['audio_track'] for w in cached['words']], [0, 1])
        self.assertEqual(selected['words'][0]['start'], 2)
        self.assertEqual(selected['tracks'], [dict(index=1, title='Guest')])
        with self.assertRaisesRegex(CensorError, 'Select the audio track'):
            analyze({**self.request, 'transcript': 'not-used.json'})

    def test_complete_cue_tails_over_resumed_speech_on_both_tracks(self):
        cue = self.work / 'cue.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=0.9', str(cue)])
        output = self.work / 'cue.mkv'
        export(dict(document=self.document, output=str(output), format='video', sound='custom', custom_sound=str(cue)))
        for track, frequency, time in [(0, 440, 1.5), (1, 880, 2.5)]:
            self.assertGreater(self.amplitude(output, track, time, frequency), .08)
            self.assertGreater(self.amplitude(output, track, time, 1000), .08)
            self.assertLess(self.amplitude(output, track, time + .6, 1000), .005)

    def test_audio_mix_zero_findings_and_invalid_track(self):
        self.document['words'] = []
        output = self.work / 'mix.wav'
        export(dict(document=self.document, output=str(output), format='audio', sound='beep'))
        self.assertEqual(len(probe(output)['streams']), 1)
        for frequency in (440, 880):
            self.assertGreater(self.amplitude(output, 0, 1.1, frequency), .04)
        self.document['words'] = [dict(audio_track=9)]
        with self.assertRaisesRegex(CensorError, 'unknown audio track'):
            self.render('invalid.mkv')
        self.assertFalse((self.work / 'invalid.mkv').exists())
