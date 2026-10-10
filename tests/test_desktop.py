"""Desktop contract tests with real FFmpeg; inference stays offline."""
import array
import contextlib
import csv
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from censor.desktop import MUTE_CAP, analyze, export, reviewed_ranges
from censor.ffmpeg import media_info, probe, run
from censor.models import WordTimestamp
from censor.utils import CensorError


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.work = Path(self.folder.name)
        self.source = self.work / 'аудио with spaces.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
             'sine=frequency=440:sample_rate=48000:duration=3', str(self.source)])
        self.transcript = self.work / 'review.json'
        self.transcript.write_text(json.dumps({'words': [
            dict(word='бля', start=1, end=1.3, profane=True)]}))
        with contextlib.redirect_stdout(io.StringIO()):
            self.document = analyze(dict(source=str(self.source), transcript=str(self.transcript)))

    def render(self, **overrides):
        request = dict(document=self.document, format='audio', sound='silence',
                       output=str(self.work / 'result.wav'))
        request.update(overrides)
        with contextlib.redirect_stdout(io.StringIO()):
            export(request)
        return Path(request['output'])

    def amplitude(self, path, start, frequency):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ss', str(start),
                                 '-t', '0.05', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'],
                                capture_output=True, check=True)
        samples = array.array('f', result.stdout)
        return 2 * abs(sum(x * complex(math.cos(2*math.pi*frequency*i/48000),
                                      math.sin(2*math.pi*frequency*i/48000))
                           for i, x in enumerate(samples))) / len(samples)

    def test_language_reaches_whisper_and_separates_cache_dictionary_and_history(self):
        for backend, target in [("faster-whisper", "FasterWhisperBackend"), ("mlx", "MLXWhisperBackend")]:
            with self.subTest(backend=backend), patch('censor.desktop.' + target) as engine, contextlib.redirect_stdout(io.StringIO()):
                engine.return_value.transcribe.return_value = [WordTimestamp('fuck', 1, 1.3), WordTimestamp('бля', 2, 2.3)]
                request = dict(source=str(self.source), backend=backend, cache_dir=str(self.work / 'cache'))
                ru = analyze(request)
                en = analyze({**request, 'language': 'en'})
                self.assertEqual(engine.call_args.args[1], 'en')
                self.assertEqual([w['profane'] for w in ru['words']], [False, True])
                self.assertEqual([w['profane'] for w in en['words']], [True, False])
                self.assertFalse(en['cache_hit'])
                self.assertEqual(en['language'], 'en')
                self.assertTrue(analyze({**request, 'language': 'en'})['cache_hit'])
                self.assertEqual(engine.call_count, 2)
        with (self.work / 'recognition-history/runs.csv').open(encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({row['language'] for row in rows}, {'ru', 'en'})

    def test_gigaam_english_is_rejected_before_model_download(self):
        with patch('censor.experimental_gpu.prepare') as prepare, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(CensorError, 'Russian only'):
                analyze(dict(source=str(self.source), backend='gigaam-mps', model='gigaam-v3', language='en'))
            prepare.assert_not_called()
            with self.assertRaisesRegex(CensorError, 'Russian or English'):
                analyze(dict(source=str(self.source), language='de'))

    def test_audio_probe_and_silence_export(self):
        self.assertFalse(self.document['has_video'])
        self.assertEqual(media_info(self.source, allow_audio=True).video_index, -1)
        output = self.render()
        self.assertEqual(probe(output)['streams'][0]['codec_name'], 'pcm_s24le')
        self.assertLess(self.amplitude(output, 1.1, 440), .001)
        self.assertGreater(self.amplitude(output, 1.3, 440), .1)

    def test_cue_tail_does_not_extend_mute(self):
        cue = self.work / 'long.wav'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
             'sine=frequency=1000:sample_rate=48000:duration=0.9', str(cue)])
        before = reviewed_ranges(self.document, 3)
        output = self.render(sound='custom', custom_sound=str(cue))
        self.assertEqual(before, reviewed_ranges(self.document, 3))
        self.assertGreater(self.amplitude(output, 1.5, 1000), .1)
        self.assertGreater(self.amplitude(output, 1.5, 440), .1)
        self.assertLess(self.amplitude(output, 2.1, 1000), .001)

    def test_zero_findings_still_export_and_no_clobber(self):
        self.document['words'][0]['profane'] = False
        output = self.render(sound='beep')
        self.assertGreater(self.amplitude(output, 1.1, 440), .1)
        with self.assertRaises(CensorError):
            self.render()
        with self.assertRaises(CensorError):
            self.render(output=str(self.source))

    def test_invalid_ranges_changed_source_and_audio_video_rejected(self):
        self.document['words'][0]['mute_end'] = float('nan')
        with self.assertRaises(CensorError):
            self.render()
        self.document['words'][0]['mute_end'] = 1.24
        with self.assertRaises(CensorError):
            self.render(format='video', output=str(self.work / 'result.mov'))
        self.document['fingerprint'] = 'stale'
        with self.assertRaises(CensorError):
            self.render()

    def test_cache_reused_and_manual_flags_not_reclassified(self):
        with patch('censor.desktop.FasterWhisperBackend.transcribe',
                   return_value=[WordTimestamp('бля', 1, 1.3)]) as engine, \
                contextlib.redirect_stdout(io.StringIO()):
            request = dict(source=str(self.source), cache_dir=str(self.work / 'cache'))
            first = analyze(request)
            second = analyze(request)
        engine.assert_called_once()
        self.assertTrue(first['words'][0]['profane'])
        self.assertEqual(first["words"], second["words"])
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertAlmostEqual(first['words'][0]['mute_start'], 1.06)
        with (self.work / 'recognition-history/runs.csv').open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row['cache_hit'] for row in rows}, {'False', 'True'})
        self.assertTrue(all(row['explicit_words'] == '1' and row['device'] == 'CPU' for row in rows))
        cached = next(row for row in rows if row['cache_hit'] == 'True')
        self.assertEqual(cached['recognition_seconds'], '')

    def test_history_failure_does_not_discard_recognition(self):
        with patch('censor.desktop.FasterWhisperBackend.transcribe',
                   return_value=[WordTimestamp('бля', 1, 1.3)]), \
             patch('censor.recognition_history.record_run', side_effect=OSError('disk full')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertLogs('censor.desktop', level='ERROR'):
            result = analyze(dict(source=str(self.source), cache_dir=str(self.work / 'cache')))
        self.assertTrue(result['words'][0]['profane'])

    def test_experimental_models_share_classification_cache_and_progress(self):
        from censor.experimental_gpu import MODELS
        for choice, (backend, repo, _) in MODELS.items():
            def transcribe(audio, progress):
                print('Library diagnostic')
                progress(2)
                return [WordTimestamp('въебали', 1, 1.5)]
            with self.subTest(model=choice), \
                 patch('censor.experimental_gpu.prepare', return_value=['/cached']), \
                 patch('censor.experimental_gpu.importlib.metadata.version', return_value='test'), \
                 patch('censor.desktop.ExperimentalGPUBackend.transcribe', side_effect=transcribe) as engine, \
                 contextlib.redirect_stdout(io.StringIO()) as protocol, contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                request = dict(source=str(self.source), backend=backend, model=choice,
                               cache_dir=str(self.work / 'cache'))
                first = analyze(request)
                cached = analyze(request)
            self.assertTrue(first['words'][0]['profane'])
            self.assertEqual(first['engine'], backend)
            self.assertTrue(cached['cache_hit'])
            engine.assert_called_once()
            events = [json.loads(line) for line in protocol.getvalue().splitlines()]
            self.assertTrue(any(e.get('stage') == 'Recognizing speech' and e.get('fraction', 0) > 0 for e in events))
            self.assertIn('Library diagnostic', diagnostic.getvalue())

    def test_selected_models_reach_each_engine_and_have_separate_caches(self):
        for backend, target, expected in [
            ('faster-whisper', 'FasterWhisperBackend', ['large-v3', 'large-v3-turbo']),
            ('mlx', 'MLXWhisperBackend', ['mlx-community/whisper-large-v3-mlx', 'mlx-community/whisper-large-v3-turbo'])
        ]:
            with self.subTest(backend=backend), patch('censor.desktop.' + target) as engine, contextlib.redirect_stdout(io.StringIO()):
                engine.return_value.transcribe.return_value = [WordTimestamp('бля', 1, 1.3)]
                for model, resolved in zip(['large-v3', 'large-v3-turbo'], expected):
                    request = dict(source=str(self.source), cache_dir=str(self.work / 'cache'), backend=backend, model=model)
                    first = analyze(request)
                    self.assertFalse(first['cache_hit'])
                    self.assertEqual(engine.call_args.args[0], resolved)
                    self.assertTrue(analyze(request)['cache_hit'])
                self.assertEqual(engine.call_count, 2)

    def test_json_protocol_and_video_stream_copy(self):
        source = self.work / 'video.mov'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=160x90:r=25:d=3',
             '-i', str(self.source), '-c:v', 'libx264', '-c:a', 'pcm_s16le', str(source)])
        request = self.work / 'request.json'
        request.write_text(json.dumps(dict(operation='analyze', source=str(source), transcript=str(self.transcript))))
        result = subprocess.run([sys.executable, '-m', 'censor.desktop', str(request)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[-1]['event'], 'result')
        document = events[-1]
        output = self.render(document=document, format='video', sound='beep', output=str(self.work / 'out.mov'))
        def digest(path):
            return run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c:v', 'copy',
                        '-f', 'hash', '-hash', 'sha256', '-'])
        self.assertEqual(digest(source), digest(output))

    def test_approved_reference_mute_timing(self):
        from censor.ranges import middle_ranges
        from censor.transcription import read_transcript
        root = Path(__file__).resolve().parents[1]
        reference = root / 'input.reviewed.transcript.json'
        if not reference.exists():
            self.skipTest('Local approved reference is unavailable')
        source = root / 'input.mov'
        duration = media_info(source).duration
        document = analyze(dict(source=str(source), transcript=str(reference)))
        expected = middle_ranges(read_transcript(reference, duration), duration, MUTE_CAP)
        self.assertEqual(reviewed_ranges(document, duration), expected)

    def test_whole_word_setting_mutes_edges_without_sound_length_cap(self):
        self.transcript.write_text(json.dumps({'words': [
            dict(word='бля', start=1, end=2, profane=True)]}))
        self.document = analyze(dict(source=str(self.source), transcript=str(self.transcript), censor_style='full'))
        self.assertEqual(self.document['censor_style'], 'full')
        self.assertEqual([(r.start, r.end) for r in reviewed_ranges(self.document, 3)], [(1, 2)])
        output = self.render(sound='beep')
        # The short beep ends naturally; speech stays muted for the whole word.
        self.assertLess(self.amplitude(output, 1.02, 440), .001)
        self.assertLess(self.amplitude(output, 1.8, 440), .001)
        self.assertLess(self.amplitude(output, 1.8, 1000), .001)
        self.assertGreater(self.amplitude(output, 2.1, 440), .1)
        self.assertEqual(self.document['words'][0]['mute_end'], 2)

    def test_censor_style_validation_and_cache_independence(self):
        with self.assertRaises(CensorError):
            analyze(dict(source=str(self.source), censor_style='invalid'))
        with patch('censor.desktop.FasterWhisperBackend.transcribe',
                   return_value=[WordTimestamp('бля', 1, 2)]) as engine, contextlib.redirect_stdout(io.StringIO()):
            request = dict(source=str(self.source), cache_dir=str(self.work / 'cache'))
            middle = analyze(request)
            full = analyze({**request, 'censor_style': 'full'})
        engine.assert_called_once()
        self.assertEqual(middle['censor_style'], 'middle')
        self.assertGreater(middle['words'][0]['mute_start'], 1)
        self.assertEqual(full['words'][0]['mute_start'], 1)
        self.assertEqual(full['words'][0]['mute_end'], 2)

    def test_whisperkit_selection_cache_bypass_and_shared_censoring(self):
        request = dict(source=str(self.source), cache_dir=str(self.work / 'wk-cache'), backend='whisperkit',
                       whisperkit_executable='/not-used-by-mock', whisperkit_model_folder='/not-used-by-mock')
        with patch('censor.whisperkit_backend.prepare_assets') as assets, \
             patch('censor.whisperkit_backend.cache_identity', return_value=('wk-key', {})), \
             patch('censor.whisperkit_backend.WhisperKitBackend') as native, \
             patch('censor.desktop.FasterWhisperBackend.transcribe', side_effect=AssertionError('fallback')), \
             contextlib.redirect_stdout(io.StringIO()):
            native.return_value.metrics = dict(load_seconds=1)
            native.return_value.transcribe.return_value = [WordTimestamp('бля', 1, 1.3)]
            first = analyze(request)
            cached = analyze(request)
            fresh = analyze({**request, 'bypass_cache': True})
        self.assertEqual(native.return_value.transcribe.call_count, 2)
        self.assertFalse(first['cache_hit'])
        self.assertTrue(cached['cache_hit'])
        self.assertFalse(fresh['cache_hit'])
        self.assertEqual(first['engine'], 'whisperkit')
        self.assertEqual(first['words'], self.document['words'])
        self.assertEqual(first['words'], cached['words'])
        self.assertTrue(all(call.kwargs['offline'] for call in assets.call_args_list))
