"""Language-specific word lists and explicit exceptions; no substring matching."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def normalize(word: str) -> str:
    word = unicodedata.normalize("NFKC", word).casefold().replace("ё", "е")
    # Remove stress marks, collapse expressive repetitions (including бляяя).
    word = "".join(c for c in word if not unicodedata.combining(c))
    return re.sub(r"([а-я])\1+", r"\1", word)


# A dictionary stem selects a bounded morphological family. Unlisted stems are
# exact words; users can opt into prefix matching with an explicit trailing '*'.
_EB = r"(?:въ|(?:вз|вы|до|за|из|ис|на|недо|об|от|пере|под|по|при|про|раз|рас|с|у)?ъ?)еб(?:а[а-я]*|ну[а-я]*|уч[а-я]*|ущ[а-я]*|л[а-я]*|е[тшм][а-я]*|и(?:сь|те|т[а-я]*|с[а-я]*)?|у(?:т|сь)?|ыва[а-я]*)"
_HUI = r"(?:на|ни|по|не|до|за|с)?ху(?:й[а-я]*|я[а-я]*|е[а-я]*|и[а-я]*|ю[а-я]*)"
_OHU = r"[оа]ху(?:е[а-я]*|и[а-я]*|я[а-я]*)"
_FAMILIES = {
    "бля": r"бля(?:[дт](?:ь|и[а-я]*|ск[а-я]*|ств[а-я]*|ун[а-я]*|ю[а-я]*|ям[а-я]*|ей|[а-я]*ина))?",
    "бляд": r"бля[дт](?:ь|и[а-я]*|ск[а-я]*|ств[а-я]*|ун[а-я]*|ю[а-я]*|ям[а-я]*|ей)",
    "еб": _EB,
    "пизд": r"(?:в|вы|до|за|на|от|пере|по|при|про|раз|рас|с|у)?пизд[а-я]*",
    "ху": rf"(?:{_HUI}|{_OHU})",
    "хуй": _HUI,
    "нахуй": r"нахуй",
    "оху": _OHU,
    "заеб": r"заеб[а-я]*",
    "долбоеб": r"долбоеб[а-я]*",
    "мудак": r"муда(?:к[а-я]*|ч[а-я]*)",
}


class ProfanityMatcher:
    def __init__(self, entries: list[str], language="ru", exceptions=None):
        self.patterns = self.compile_patterns(entries, language)
        self.exceptions = self.compile_patterns(exceptions or [], language, families=False)
        self.rules = dict(language=language, censor=entries, allow=exceptions or [])

    @staticmethod
    def compile_patterns(entries, language, families=True):
        if language not in {"ru", "en"}:
            raise ValueError("Choose Russian or English.")
        if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
            raise ValueError("Word lists must contain one string per entry.")
        alphabet = "а-я" if language == "ru" else "a-z"
        patterns = []
        for entry in entries:
            entry = entry.split("#", 1)[0].strip()
            if not entry:
                continue
            stem = normalize(entry[:-1] if entry.endswith("*") else entry)
            if not re.fullmatch(f"[{alphabet}]+", stem):
                raise ValueError(f"Invalid blacklist entry: {entry!r}; use a {language} word or stem*.")
            forms = _FAMILIES if language == "ru" and families else {}
            pattern = (re.escape(stem) + f"[{alphabet}]*" if entry.endswith("*")
                       else forms.get(stem, re.escape(stem)))
            patterns.append(re.compile(pattern))
        return patterns

    def identity(self):
        return hashlib.sha256(json.dumps(self.rules, sort_keys=True, ensure_ascii=False).encode() +
                              Path(__file__).read_bytes()).hexdigest()

    @classmethod
    def from_request(cls, language, rules=None):
        if rules is None:
            rules = {}
        if not isinstance(rules, dict):
            raise ValueError("Invalid word lists.")
        entries = rules.get("censor")
        if entries is None:
            entries = cls.dictionary_path(language).read_text(encoding="utf-8-sig").splitlines()
        exceptions = rules.get("allow", [])
        if not isinstance(exceptions, list):
            raise ValueError("Exceptions must be a list of words.")
        return cls(entries, language, exceptions)

    @classmethod
    def from_file(cls, path: Path, language="ru") -> "ProfanityMatcher":
        return cls(path.read_text(encoding="utf-8-sig").splitlines(), language)

    @staticmethod
    def dictionary_path(language="ru") -> Path:
        if language not in {"ru", "en"}:
            raise ValueError("Choose Russian or English.")
        return Path(__file__).resolve().parents[1] / ("profanity.en.txt" if language == "en" else "profanity.txt")

    @classmethod
    def for_language(cls, language="ru") -> "ProfanityMatcher":
        return cls.from_file(cls.dictionary_path(language), language)

    def matches(self, word: str) -> bool:
        normalized = normalize(word)
        # Retain script boundaries: mixed-script strings are not silently repaired.
        chunks = re.findall(r"[^\W\d_]+(?:[-‐‑–—][^\W\d_]+)*", normalized)
        for chunk in chunks:
            parts = re.split(r"[-‐‑–—]", chunk)
            if any(pattern.fullmatch(candidate) for candidate in [chunk, "".join(parts)]
                   for pattern in self.exceptions):
                continue
            candidates = [*parts, "".join(parts)]  # ху-й, за-ебало, кто-то
            if any(pattern.fullmatch(candidate) for candidate in candidates for pattern in self.patterns):
                return True
        return False
