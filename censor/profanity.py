"""Conservative whole-token Russian morphology, never arbitrary substring matching."""
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
    def __init__(self, entries: list[str]):
        self.patterns: list[re.Pattern] = []
        for entry in entries:
            entry = entry.split("#", 1)[0].strip()
            if not entry:
                continue
            stem = normalize(entry.rstrip("*"))
            if not re.fullmatch(r"[а-я]+", stem):
                raise ValueError(f"Invalid blacklist entry: {entry!r}; use a Russian word or stem*.")
            pattern = (re.escape(stem) + r"[а-я]*" if entry.endswith("*")
                       else _FAMILIES.get(stem, re.escape(stem)))
            self.patterns.append(re.compile(pattern))

    @classmethod
    def from_file(cls, path: Path) -> "ProfanityMatcher":
        return cls(path.read_text(encoding="utf-8-sig").splitlines())

    def matches(self, word: str) -> bool:
        normalized = normalize(word)
        # Retain script boundaries: mixed-script strings are not silently repaired.
        chunks = re.findall(r"[^\W\d_]+(?:[-‐‑–—][^\W\d_]+)*", normalized)
        for chunk in chunks:
            parts = re.split(r"[-‐‑–—]", chunk)
            candidates = [*parts, "".join(parts)]  # ху-й, за-ебало, кто-то
            if any(pattern.fullmatch(candidate) for candidate in candidates for pattern in self.patterns):
                return True
        return False
