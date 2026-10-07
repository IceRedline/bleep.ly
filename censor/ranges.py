import math
from .models import CensorRange, WordTimestamp


def middle_ranges(words: list[WordTimestamp], duration: float, sound_duration: float | None,
                  fraction: float = .6) -> list[CensorRange]:
    """Start inside each word, then allow the entire natural cue to finish."""
    if not math.isfinite(fraction) or not 0 < fraction <= 1:
        raise ValueError("Censor fraction must be between 0 (exclusive) and 1.")
    if sound_duration is not None and (not math.isfinite(sound_duration) or sound_duration <= 0):
        raise ValueError("Sound duration must be finite and positive.")
    selected = []
    for word in words:
        if not word.profane:
            continue
        start, end = max(0, word.start), min(duration, word.end)
        if end <= start:
            continue
        length = (end - start) * fraction
        if sound_duration is not None:
            length = min(length, sound_duration)
        center = (start + end) / 2
        selected.append(WordTimestamp(word.word, center - length / 2, center + length / 2, True))
    merged = censor_ranges(selected, duration, before=0, after=0, merge_gap=0)
    if sound_duration is None:
        return merged
    return include_full_sound(merged, duration, sound_duration)


def include_full_sound(ranges: list[CensorRange], duration: float, sound_duration: float) -> list[CensorRange]:
    """Extend mute to fit the cue; near EOF move it earlier instead of clipping."""
    if not ranges:
        return []
    if sound_duration > duration:
        raise ValueError("Censor sound is longer than the video; choose a shorter sound to play it in full.")
    extended = []
    for item in ranges:
        start = max(0, min(item.start, duration - sound_duration))
        end = max(item.end, start + sound_duration)
        extended.append(WordTimestamp("", start, end, True))
    # Nearby words share one complete cue, never overlapping copies.
    return censor_ranges(extended, duration, before=0, after=0, merge_gap=0)


def censor_ranges(words: list[WordTimestamp], duration: float, before: float = .05,
                  after: float = .08, merge_gap: float = .02) -> list[CensorRange]:
    if any(not math.isfinite(x) or x < 0 for x in (duration, before, after, merge_gap)):
        raise ValueError("Duration, padding and merge gap must be finite and nonnegative.")
    ranges = sorted(CensorRange(max(0, w.start - before), min(duration, w.end + after))
                    for w in words if w.profane and w.end > w.start)
    result: list[CensorRange] = []
    for item in ranges:
        if item.end <= item.start:
            continue
        if result and item.start <= result[-1].end + merge_gap + 1e-9:
            result[-1] = CensorRange(result[-1].start, max(result[-1].end, item.end))
        else:
            result.append(item)
    return result
