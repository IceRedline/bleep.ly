"""Compare bounded export mixing against the original FFmpeg graph."""
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from censor.audio import bed_filter, filter_graph, new_output, prepare_sound
from censor.desktop import export, fingerprint
from censor.ffmpeg import input_args, media_info, run, sound_duration
from censor.models import CensorRange
from censor.stream_mix import cue_samples, render_track
from censor.utils import CensorError


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class StreamMixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.source = self.work / 'source.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
             'aevalsrc=0.9*sin(2*PI*440*t)|0.7*sin(2*PI*730*t):s=48000:d=4.07',
             '-c:a', 'pcm_f32le', str(self.source)])
        self.info = media_info(self.source, allow_audio=True)
        raw = self.work / 'raw.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
             'sine=frequency=1700:sample_rate=48000:duration=1.2', '-af', 'volume=7', str(raw)])
        self.cue = self.work / 'cue.wav'
        prepare_sound(raw, self.cue, sound_duration(raw))

    def pcm(self, path):
        return np.frombuffer(subprocess.check_output(
            ['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le', '-']), dtype='<f4')

    def compare(self, ranges, cue):
        graph = self.work / 'reference.ffgraph'
        graph.write_text(filter_graph(self.info, ranges, 'mute', -30, sound_duration(cue)) if cue else
                         f'[0:{self.info.audio_index}]{bed_filter(self.info, ranges, "mute", -30)}[out]')
        reference = self.work / 'reference.wav'
        actual = self.work / 'actual.wav'
        for path in [reference, actual]:
            path.unlink(missing_ok=True)
        run(['ffmpeg', '-v', 'error', '-nostdin', *input_args(self.source, self.info),
             *(['-i', str(cue)] if cue else []), '-filter_complex_script', str(graph),
             '-map', '[out]', '-c:a', 'pcm_s24le', str(reference)])
        with cue_samples(cue, self.work) as data:
            render_track(self.source, actual, self.info, ranges, data)
        expected, result = self.pcm(reference), self.pcm(actual)
        self.assertEqual(result.shape, expected.shape)
        self.assertLess(float(np.max(np.abs(result - expected))), 3e-6)

    def test_full_cues_overlapping_fades_and_block_boundaries_match_reference(self):
        self.compare([CensorRange(0, .08), CensorRange(.983123456, 1.004123456),
                      CensorRange(1.008, 1.15), CensorRange(1.99, 2.08),
                      CensorRange(3.97, 4.07)], self.cue)

    def test_dense_cues_and_silence_match_reference(self):
        ranges = [CensorRange(i * .03 + .004, i * .03 + .025) for i in range(130)]
        self.compare(ranges, self.cue)
        self.compare(ranges, None)
        self.compare([], None)

    def test_compressed_audio_and_nonzero_video_start_match_reference(self):
        video = self.work / 'offset.mkv'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=160x90:r=25:d=4.07',
             '-itsoffset', '0.137', '-i', str(self.source), '-map', '0:v:0', '-map', '1:a:0',
             '-c:v', 'mpeg4', '-c:a', 'aac', '-output_ts_offset', '3', str(video)])
        self.source = video
        self.info = media_info(video)
        self.assertGreater(self.info.start, 2)
        self.compare([CensorRange(.18, .3), CensorRange(.993, 1.17), CensorRange(3.8, 4)], self.cue)

    def test_cancel_stops_both_workers_and_does_not_publish(self):
        processes = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        def cancel(_):
            raise KeyboardInterrupt()
        output = self.work / 'cancelled.wav'
        with patch('censor.stream_mix.subprocess.Popen', side_effect=launch):
            with self.assertRaises(KeyboardInterrupt), new_output(output) as staged:
                render_track(self.source, staged, self.info, [], None, cancel)
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(p.poll() is not None for p in processes))
        self.assertFalse(output.exists())

    def test_encoder_failure_is_reported_and_not_published(self):
        output = self.work / 'invalid.unknown'
        with self.assertRaises(CensorError), new_output(output) as staged:
            render_track(self.source, staged, self.info, [], None)
        self.assertFalse(output.exists())

    def test_single_track_export_does_not_write_a_full_intermediate(self):
        document = dict(source=str(self.source), fingerprint=fingerprint(self.source),
                        tracks=[dict(index=0)], words=[])
        original = render_track
        outputs = []
        def record(*args, **kwargs):
            outputs.append(args[1])
            return original(*args, **kwargs)
        destination = self.work / 'export.wav'
        with patch('censor.desktop.render_track', side_effect=record), contextlib.redirect_stdout(io.StringIO()):
            export(dict(document=document, output=str(destination), format='audio', sound='silence'))
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].parent.parent, destination.parent.resolve())
        self.assertEqual(len(self.pcm(destination)), round(self.info.duration * 48000) * 2)
