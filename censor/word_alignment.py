"""Acoustic word timing with bounded retries for ambiguous repeated speech."""
from dataclasses import replace
import math

from .utils import CensorError

RATE = 16000
MAX_START_SHIFT = .6
# The pinned Qwen aligner quantizes timestamps in 80 ms steps. Allow that
# rounding, but reject spans detached from the recognizer's word interval.
MAX_SPAN_GAP = .08


class WordAligner:
    def __init__(self, model_path, device="gpu"):
        import mlx.core as mx
        from mlx_qwen3_asr.forced_aligner import ForcedAligner, ForcedAlignTextProcessor
        if device not in {"cpu", "gpu"}:
            raise CensorError("Choose CPU or GPU for word alignment.")
        if device == "gpu" and not mx.metal.is_available():
            raise CensorError("Apple Metal GPU is unavailable for word alignment.")
        mx.set_default_device(mx.cpu if device == "cpu" else mx.gpu)
        if device == "cpu":
            mx.disable_compile()
        self.backend = ForcedAligner(model_path=model_path, dtype=mx.float32 if device == "cpu" else mx.float16)
        self.tokenize = ForcedAlignTextProcessor.tokenize_text
        self.metrics = dict(words=0, local_retries=0, native_fallbacks=0)

    def _align(self, audio, words):
        groups = [self.tokenize(w.word, 'Russian') for w in words]
        tokens = [token for group in groups for token in group]
        if not tokens:
            return []
        aligned = self.backend.align(audio, ' '.join(tokens), 'Russian')
        if [w.text for w in aligned] != tokens:
            raise CensorError("Word alignment returned a different transcript; reopen the file to retry.")
        result = []
        index = 0
        for word, group in zip(words, groups):
            if group:
                result.append(replace(word, start=float(aligned[index].start_time),
                                      end=float(aligned[index + len(group) - 1].end_time)))
                index += len(group)
        return result

    @staticmethod
    def _plausible(word, original, duration):
        return (math.isfinite(word.start) and math.isfinite(word.end)
                and 0 <= word.start < word.end <= duration + 1e-6
                and word.end - word.start >= .04 - 1e-6
                and abs(word.start - original.start) <= MAX_START_SHIFT
                and word.end <= original.end + MAX_START_SHIFT
                and max(original.start - word.end, word.start - original.end) <= MAX_SPAN_GAP + 1e-6)

    def align(self, audio, words):
        # Punctuation remains attached to lexical words, but stand-alone dashes
        # cannot be assigned acoustic boundaries and are not review words.
        words = [w for w in words if self.tokenize(w.word, 'Russian')]
        aligned = self._align(audio, words)
        duration = len(audio) / RATE
        result = []
        for index, (original, candidate) in enumerate(zip(words, aligned)):
            self.metrics['words'] += 1
            if not self._plausible(candidate, original, duration):
                self.metrics['local_retries'] += 1
                lo = max(0, round((original.start - MAX_START_SHIFT) * RATE))
                hi = min(len(audio), round((original.end + .4) * RATE))
                indices = [i for i, w in enumerate(words) if i == index
                           or lo / RATE <= w.start < w.end <= hi / RATE]
                local_words = [replace(words[i], start=words[i].start - lo / RATE,
                                       end=words[i].end - lo / RATE) for i in indices]
                if hi > lo:
                    retry = self._align(audio[lo:hi], local_words)[indices.index(index)]
                    candidate = replace(retry, start=retry.start + lo / RATE, end=retry.end + lo / RATE)
                if not self._plausible(candidate, original, duration):
                    # Recognition can contain a word the aligner cannot locate.
                    # Keep it reviewable instead of dropping it or censoring an
                    # unrelated utterance. Record this explicitly in run metadata.
                    self.metrics['native_fallbacks'] += 1
                    candidate = original
            result.append(candidate)
        return result
