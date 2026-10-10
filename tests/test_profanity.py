import unittest
from pathlib import Path
from censor.profanity import ProfanityMatcher


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ProfanityMatcher.from_file(Path(__file__).resolve().parents[1] / "profanity.txt")

    def test_positive_examples(self):
        words = "блять блядь бля бляяя блядский ебать ёбать ебаный ёбаный ебануться заебало заёбало наебался пиздец пизда пиздатый хуй хуя хуйню нахуй охуеть ахуеть охуенно долбоеб долбоёб мудак мудачок ебёт ебись ебут отъебись выебал бляди".split()
        for word in words:
            with self.subTest(word=word):
                self.assertTrue(self.matcher.matches(word))

    def test_false_positives(self):
        words = "художник хуже хулиган хунта хурма худая хлеб хлебать учеба учебник ребенок ребята небо мебель серебро колебать колебание потреблять употреблять корабля рубля бляшка блямба бляха страхуй подстрахуй страхуя хулить охуж обедать заехать".split()
        for word in words:
            with self.subTest(word=word):
                self.assertFalse(self.matcher.matches(word))

    def test_variants(self):
        for word in ["«БЛЯДЬ!»", "ёба́ть", "хуууй", "ху-й", "за-ебало", "ну, блядь", "БЛЯЯЯЯ!!!", "по-хую"]:
            with self.subTest(word=word):
                self.assertTrue(self.matcher.matches(word))

    def test_inflections_missed_in_model_comparison(self):
        for word in ["въебали", "въебу.", "въебанутый?", "ебём,", "проебем", "разъебём.", "Схуели."]:
            with self.subTest(word=word):
                self.assertTrue(self.matcher.matches(word))
        for word in ["веб", "вебу", "вебка", "вебку", "вебинар", "схуднуть", "схудели", "схулиганить", "небесная", "потребление"]:
            with self.subTest(word=word):
                self.assertFalse(self.matcher.matches(word))

    def test_custom_entries_are_not_substrings(self):
        matcher = ProfanityMatcher(["плохой", "руг* # opt-in prefix", "# ignored"])
        self.assertTrue(matcher.matches("плохой"))
        self.assertFalse(matcher.matches("неплохой"))
        self.assertTrue(matcher.matches("ругательство"))
        self.assertFalse(matcher.matches("друг"))

    def test_invalid_blacklist(self):
        with self.assertRaises(ValueError):
            ProfanityMatcher([".*"])
