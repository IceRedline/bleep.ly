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


class EnglishMatcherTests(unittest.TestCase):
    def test_english_words_inflections_and_script_boundaries(self):
        matcher = ProfanityMatcher.for_language("en")
        for word in ["FUCK!", "fucking", "motherfucker", "bullshit", "assholes", "shit’s", "fuck-ing"]:
            with self.subTest(word=word):
                self.assertTrue(matcher.matches(word))
        for word in ["Scunthorpe", "class", "assistant", "cocktail", "Dickinson", "shitake", "бля", "fуck"]:
            with self.subTest(word=word):
                self.assertFalse(matcher.matches(word))
        self.assertFalse(ProfanityMatcher.for_language("ru").matches("fuck"))
        with self.assertRaises(ValueError):
            ProfanityMatcher.for_language("de")


class CustomWordListTests(unittest.TestCase):
    def test_exceptions_override_forms_but_do_not_suppress_other_words(self):
        matcher = ProfanityMatcher(['еб'], exceptions=['ебать'])
        self.assertFalse(matcher.matches('ЕБАТЬ!'))
        self.assertTrue(matcher.matches('ебаный'))
        self.assertTrue(matcher.matches('ебать ебаный'))
        english = ProfanityMatcher(['fuck*', 'cock'], 'en', ['fucking', 'cocktail'])
        self.assertFalse(english.matches('FUCKING!'))
        self.assertFalse(english.matches('cocktail'))
        self.assertTrue(english.matches('fucker'))
        self.assertFalse(ProfanityMatcher(['fuck*'], 'en', ['fuck*']).matches('fucker'))

    def test_full_replacement_empty_list_validation_and_identity(self):
        matcher = ProfanityMatcher.from_request('en', {'censor': ['banana'], 'allow': []})
        self.assertTrue(matcher.matches('banana'))
        self.assertFalse(matcher.matches('fuck'))
        self.assertFalse(ProfanityMatcher.from_request('en', {'censor': []}).matches('fuck'))
        self.assertNotEqual(matcher.identity(), ProfanityMatcher.from_request('en').identity())
        for rules in [{'censor': ['bad**']}, {'censor': 'word'}, {'allow': 'word'}, {'allow': [3]}]:
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                ProfanityMatcher.from_request('en', rules)
