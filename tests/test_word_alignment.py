import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from censor.models import WordTimestamp as Word
from censor.utils import CensorError
from censor.word_alignment import WordAligner


def aligned(text, start, end):
    return SimpleNamespace(text=text, start_time=start, end_time=end)


class WordAlignmentTests(unittest.TestCase):
    def test_cpu_alignment_never_selects_gpu(self):
        mx = Mock()
        mx.metal.is_available.return_value = False
        factory = Mock()
        with patch.dict('sys.modules', {'mlx': SimpleNamespace(core=mx), 'mlx.core': mx,
                'mlx_qwen3_asr.forced_aligner': SimpleNamespace(
                    ForcedAligner=factory, ForcedAlignTextProcessor=Mock())}):
            WordAligner('/cached-aligner', device='cpu')
        mx.metal.is_available.assert_not_called()
        mx.set_default_device.assert_called_once_with(mx.cpu)
        mx.disable_compile.assert_called_once_with()
        factory.assert_called_once_with(model_path='/cached-aligner', dtype=mx.float32)

    def aligner(self, outputs):
        a = WordAligner.__new__(WordAligner)
        a.backend = Mock()
        a.backend.align.side_effect = outputs
        a.tokenize = lambda text, language: [text.strip('.,!')] if text.strip('.,!') else []
        a.metrics = dict(words=0, local_retries=0, native_fallbacks=0)
        return a

    def test_acoustic_span_replaces_punctuation_delay_but_keeps_text(self):
        a = self.aligner([[aligned('блядь', .6, 1.16)]])
        result = a.align([0] * 32000, [Word('блядь.', .8, 1.72, True)])
        self.assertEqual(result, [Word('блядь.', .6, 1.16, True)])
        self.assertEqual(a.metrics['local_retries'], 0)

    def test_wrong_repeated_utterance_is_retried_in_bounded_context(self):
        a = self.aligner([[aligned('блядь', 1.52, 1.68)], [aligned('блядь', .4, .96)]])
        result = a.align([0] * 80000, [Word('блядь.', 2.8, 3.72)])
        self.assertAlmostEqual(result[0].start, 2.6)
        self.assertAlmostEqual(result[0].end, 3.16)
        self.assertEqual(len(a.backend.align.call_args.args[0]), 30720)
        self.assertEqual(a.metrics, dict(words=1, local_retries=1, native_fallbacks=0))

    def test_unresolved_word_stays_reviewable_and_is_counted(self):
        a = self.aligner([[aligned('word', 1, 1)], [aligned('word', .6, .6)]])
        word = Word('word', 1, 1.4)
        self.assertEqual(a.align([0] * 32000, [word]), [word])
        self.assertEqual(a.metrics['native_fallbacks'], 1)

    def test_zero_duration_retry_cannot_move_word_into_preceding_silence(self):
        # A real GigaAM word at 21.86 s, relative to its window at 20.104 s.
        # Qwen first collapses it to one timestamp, then places the retry
        # 0.52 s early, entirely before the recognizer's word interval.
        a = self.aligner([[aligned('Блядь', 1.92, 1.92)], [aligned('Блядь', .08, .24)]])
        word = Word('Блядь,', 1.7586461538461537, 2.0384307692307693, True)
        self.assertEqual(a.align([0] * 83136, [word]), [word])
        self.assertEqual(a.metrics, dict(words=1, local_retries=1, native_fallbacks=1))

    def test_disjoint_spans_within_start_shift_limit_are_retried(self):
        word = Word('word', 1, 1.2)
        for start, end in [(.48, .64), (1.56, 1.72)]:
            with self.subTest(start=start, end=end):
                a = self.aligner([[aligned('word', start, end)], [aligned('word', .6, .84)]])
                result = a.align([0] * 32000, [word])
                self.assertAlmostEqual(result[0].start, 1)
                self.assertAlmostEqual(result[0].end, 1.24)
                self.assertEqual(a.metrics, dict(words=1, local_retries=1, native_fallbacks=0))

    def test_short_native_token_allows_one_alignment_frame_of_rounding(self):
        a = self.aligner([[aligned('word', 1.16, 1.32)]])
        self.assertEqual(a.align([0] * 32000, [Word('word', 1.04, 1.08)]),
                         [Word('word', 1.16, 1.32)])
        self.assertEqual(a.metrics['local_retries'], 0)

    def test_incomplete_or_mismatched_transcript_is_not_silently_zipped(self):
        for values in [[], [aligned('another', .5, 1)]]:
            a = self.aligner([values])
            with self.assertRaisesRegex(CensorError, 'different transcript'):
                a.align([0] * 32000, [Word('word', .5, 1)])

    def test_nonfinite_or_out_of_bounds_results_cannot_escape_into_review(self):
        for start, end in [(float('nan'), 1), (.5, float('inf')), (-.1, .5), (1, 3)]:
            a = self.aligner([[aligned('word', start, end)], [aligned('word', 0, 0)]])
            word = Word('word', .5, 1)
            self.assertEqual(a.align([0] * 32000, [word]), [word])

    def test_empty_or_punctuation_only_transcript_needs_no_alignment(self):
        a = self.aligner([])
        self.assertEqual(a.align([0] * 16000, [Word('!', .5, .6)]), [])
        a.backend.align.assert_not_called()
