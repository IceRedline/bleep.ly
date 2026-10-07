import unittest
from censor.models import WordTimestamp, CensorRange
from censor.ranges import censor_ranges, middle_ranges
from censor.transcription import parse_words
from censor.utils import CensorError, timestamp


class RangeTests(unittest.TestCase):
    def test_middle_preserves_word_edges_and_caps_to_sound(self):
        result = middle_ranges([WordTimestamp("блять", 0, .72, True),
                                WordTimestamp("похуй", 9.28, 9.6, True)], 20, .383)
        self.assertAlmostEqual(result[0].start, .1685)
        self.assertAlmostEqual(result[0].end, .5515)
        self.assertAlmostEqual(result[1].duration, .192)
        self.assertGreater(result[1].start, 9.28)
        self.assertLess(result[1].end, 9.6)

    def test_middle_overlaps_do_not_exceed_sound(self):
        result = middle_ranges([WordTimestamp("мат", 0, 1, True), WordTimestamp("мат", .1, 1.1, True)], 2, .2)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].duration, .2)

    def test_middle_near_end_does_not_expand_mute(self):
        result = middle_ranges([WordTimestamp("мат", 1.9, 2, True)], 2, .4)
        self.assertAlmostEqual(result[0].start, 1.92)
        self.assertAlmostEqual(result[0].end, 1.98)

    def test_padding(self):
        result = censor_ranges([WordTimestamp("мат", 10.2, 10.65, True)], 20, .05, .1)
        self.assertAlmostEqual(result[0].start, 10.15)
        self.assertAlmostEqual(result[0].end, 10.75)

    def test_overlapping_adjacent_unsorted_and_nested(self):
        words = [WordTimestamp("блядь", 1.32, 1.7, True), WordTimestamp("ебать", 1, 1.3, True),
                 WordTimestamp("бля", 1.1, 1.2, True), WordTimestamp("мат", 1.84, 2, True)]
        ranges = censor_ranges(words, 3)
        self.assertEqual(len(ranges), 1)
        self.assertAlmostEqual(ranges[0].start, .95)
        self.assertAlmostEqual(ranges[0].end, 2.08)

    def test_separate_clean_words_and_edges(self):
        words = [WordTimestamp("бля", 0, .1, True), WordTimestamp("норм", .2, 1, False),
                 WordTimestamp("хуй", 1.8, 2, True)]
        self.assertEqual(censor_ranges(words, 2), [CensorRange(0, .18), CensorRange(1.75, 2)])

    def test_empty_and_invalid(self):
        self.assertEqual(censor_ranges([], 2), [])
        with self.assertRaises(ValueError):
            censor_ranges([], 2, before=float("nan"))

    def test_invalid_transcript(self):
        for overrides in [{"start": -1}, {"end": 0}, {"end": 12}, {"start": float("nan")},
                          {"start": True}, {"profane": "false"}, {"word": ""}]:
            with self.subTest(overrides=overrides), self.assertRaises(CensorError):
                parse_words({"words": [{"word": "бля", "start": 0, "end": 1, "profane": False, **overrides}]}, 10)

    def test_manual_flags_and_time_carry(self):
        words = parse_words({"words": [{"word": "бля", "start": 0, "end": 1, "profane": False}]}, 10)
        self.assertFalse(words[0].profane)
        self.assertEqual(timestamp(59.9996), "01:00.000")
