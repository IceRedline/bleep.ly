import unittest

from censor.models import CensorRange, WordTimestamp
from censor.speakers import cue_owners, identify_reference, label_words, validate_segments
from censor.transcription import parse_words
from censor.utils import CensorError


class SpeakerTests(unittest.TestCase):
    def test_reference_requires_clear_dominant_voice(self):
        segments = [dict(start=0, end=20, speaker=2), dict(start=20, end=30, speaker=1)]
        mine, metadata = identify_reference(segments, 2, 12)
        self.assertEqual(mine, 2)
        self.assertEqual(metadata['dominance'], 1)
        with self.assertRaisesRegex(CensorError, 'multiple prominent'):
            identify_reference(segments, 15, 25)
        with self.assertRaisesRegex(CensorError, 'less than 2'):
            identify_reference(segments, 40, 50)

    def test_overlap_and_missing_speech_remain_unknown(self):
        segments = [dict(start=0, end=2, speaker=0), dict(start=1, end=4, speaker=1),
                    dict(start=2, end=4, speaker=2)]
        words = [WordTimestamp('бля', a, b, True) for a, b in [(0, .5), (1.2, 1.5), (2.5, 3), (5, 6)]]
        result = label_words(words, segments, 0)
        self.assertEqual([w.speaker for w in result], ['me', 'unknown', 'others', 'unknown'])
        # Two other speakers in the same span still have at most 100% coverage.
        self.assertEqual(result[2].speaker_coverage, 1)
        self.assertEqual([(w.start, w.end, w.profane) for w in result],
                         [(w.start, w.end, w.profane) for w in words])

    def test_merged_different_speakers_use_unknown_without_extra_cues(self):
        words = [WordTimestamp('бля', 1, 1.3, True, 'me'), WordTimestamp('бля', 1.2, 1.5, True, 'others')]
        self.assertEqual(cue_owners(words, [CensorRange(1, 1.5)]), ['unknown'])
        self.assertEqual(cue_owners(words, [CensorRange(1.31, 1.5)]), ['others'])

    def test_manual_labels_roundtrip_and_validate(self):
        word = dict(word='бля', start=1, end=2, profane=True, speaker='others', speaker_coverage=.8)
        self.assertEqual(parse_words(dict(words=[word]), 3)[0].speaker, 'others')
        for invalid in [dict(speaker='person42'), dict(speaker=[]), dict(speaker_coverage=float('nan')), dict(speaker_coverage=2)]:
            with self.assertRaises(CensorError):
                parse_words(dict(words=[dict(word, **invalid)]), 3)
        self.assertIsNone(parse_words(dict(words=[dict(word='бля', start=1, end=2, profane=True)]), 3)[0].speaker)

    def test_invalid_segment_data_rejected(self):
        for bad in [None, [dict(start=-1, end=2, speaker=0)], [dict(start=1, end=9, speaker=0)],
                    [dict(start=1, end=2, speaker=True)]]:
            with self.assertRaises(CensorError):
                validate_segments(bad, 3)
