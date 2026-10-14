import unittest

from censor.models import WordTimestamp as Word
from censor.speech_chunks import SpeechWindow, append_window_words, speech_windows


class SpeechChunkTests(unittest.TestCase):
    def test_context_keeps_a_word_cut_by_the_original_boundary_once(self):
        windows = speech_windows([{'start': 0, 'end': 320000}, {'start': 320000, 'end': 640000}], 640000)
        self.assertEqual([(w.start, w.end) for w in windows], [(0, 336000), (304000, 640000)])
        result = []
        append_window_words(result, [Word('вообще', 19.7, 19.9), Word('охуеть.', 19.99, 20.3)], windows[0])
        append_window_words(result, [Word('вообще', 19.72, 19.92), Word('охуеть.', 20.01, 20.32),
                                     Word('Ну', 20.4, 20.5)], windows[1])
        self.assertEqual([w.word for w in result], ['вообще', 'охуеть.', 'Ну'])

    def test_timestamp_jitter_across_boundary_does_not_duplicate_a_word(self):
        result = [Word('блядь,', 19.8, 20.1)]
        append_window_words(result, [Word('блядь.', 19.9, 20.2), Word('дальше', 20.3, 20.6)],
                            SpeechWindow(304000, 640000, 20, 40))
        self.assertEqual([w.word for w in result], ['блядь.', 'дальше'])

    def test_repeated_words_are_not_collapsed(self):
        result = [Word('да', 19.8, 19.95)]
        append_window_words(result, [Word('да', 20.02, 20.16), Word('да', 20.2, 20.4)],
                            SpeechWindow(304000, 640000, 20, 40))
        self.assertEqual(len(result), 3)

    def test_file_edges_and_speech_padding_are_owned(self):
        windows = speech_windows([{'start': 8000, 'end': 160000}, {'start': 240000, 'end': 312000}], 320000)
        self.assertEqual([(w.own_start, w.own_end) for w in windows], [(0, 12.5), (12.5, 20)])
        result = []
        append_window_words(result, [Word('start', .1, .3)], windows[0])
        append_window_words(result, [Word('end', 19.7, 19.99)], windows[1])
        self.assertEqual([w.word for w in result], ['start', 'end'])
        self.assertEqual(speech_windows([], 16000), [])

    def test_two_seconds_of_context_stays_under_backend_limit(self):
        windows = speech_windows([{'start': 160000, 'end': 480000}], 640000)
        self.assertEqual((windows[0].end - windows[0].start) / 16000, 22)
