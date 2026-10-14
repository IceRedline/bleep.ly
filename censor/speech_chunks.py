"""Overlapping recognition windows with one owner for each boundary word."""
from dataclasses import dataclass
import unicodedata

from .models import WordTimestamp

SAMPLE_RATE = 16000
CONTEXT_SECONDS = 1


@dataclass(frozen=True)
class SpeechWindow:
    start: int
    end: int
    own_start: float
    own_end: float


def speech_windows(chunks, sample_count):
    """Keep VAD cores, adding context without exceeding GigaAM's 25 s limit.

    Cores are at most 20 s. Adjacent windows share two seconds; their ownership
    boundary remains halfway between the unpadded cores. Context at file edges
    and in the padding around VAD speech is also eligible for recognition.
    """
    padding = CONTEXT_SECONDS * SAMPLE_RATE
    return [SpeechWindow(max(0, chunk['start'] - padding), min(sample_count, chunk['end'] + padding),
                         (chunks[i - 1]['end'] + chunk['start']) / 2 / SAMPLE_RATE if i else 0,
                         (chunk['end'] + chunks[i + 1]['start']) / 2 / SAMPLE_RATE
                         if i + 1 < len(chunks) else sample_count / SAMPLE_RATE)
            for i, chunk in enumerate(chunks)]


def lexical_key(text):
    return ''.join(c for c in text.casefold() if unicodedata.category(c)[0] in 'LN')


def append_window_words(result: list[WordTimestamp], words: list[WordTimestamp], window: SpeechWindow):
    """Assign by midpoint, then reconcile a boundary duplicate caused by jitter.

    Deduplication only compares different windows. Repeated words within one
    window, or successive occurrences with nonoverlapping spans, stay intact.
    """
    selected = [w for w in words if window.own_start <= (w.start + w.end) / 2 < window.own_end]
    left = next((i for i in range(len(result) - 1, -1, -1) if lexical_key(result[i].word)), None)
    right = next((i for i, w in enumerate(selected) if lexical_key(w.word)), None)
    if left is not None and right is not None:
        a, b = result[left], selected[right]
        overlap = min(a.end, b.end) - max(a.start, b.start)
        shortest = min(a.end - a.start, b.end - b.start)
        if (lexical_key(a.word) == lexical_key(b.word) and shortest > 0
                and overlap > shortest / 2 and abs((a.start + a.end - b.start - b.end) / 2) < .2):
            # The newer window has more following context for this boundary word.
            result[left] = b
            selected.pop(right)
    result.extend(selected)
