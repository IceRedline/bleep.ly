"""Local diarization and conservative assignment to 'me / others / unknown'."""
import importlib.metadata
import json
from dataclasses import replace
from pathlib import Path

from .transcription import file_hash
from .utils import CensorError, finite_number, write_json

SEGMENTATION = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
EMBEDDING = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


def validate_segments(data, duration):
    if not isinstance(data, list):
        raise CensorError("Speaker segments must be a list.")
    result = []
    for item in data:
        if not isinstance(item, dict):
            raise CensorError("Invalid speaker segment.")
        start = finite_number(item.get("start"), "speaker start")
        end = finite_number(item.get("end"), "speaker end")
        speaker = item.get("speaker")
        if not isinstance(speaker, int) or isinstance(speaker, bool) or speaker < 0:
            raise CensorError("Speaker id must be a nonnegative integer.")
        if not 0 <= start < end <= duration + .1:
            raise CensorError("Speaker segment is outside the audio timeline.")
        result.append(dict(start=start, end=min(end, duration), speaker=speaker))
    return sorted(result, key=lambda r: (r["start"], r["end"]))


def diarize(audio: Path, model_dir: Path, count: int, cache_dir: Path, progress,
            duration: float, save_cache: bool = True):
    try:
        import numpy as np
        import wave
        import sherpa_onnx as sherpa
    except ImportError as exc:
        raise CensorError("Install speaker dependencies: pip install -r requirements-speakers.txt") from exc
    models = [model_dir / SEGMENTATION, model_dir / EMBEDDING]
    for model in models:
        if not model.is_file():
            raise CensorError(f"Speaker model missing: {model}. See README speaker setup.")
    import hashlib
    settings = dict(audio=file_hash(audio), speakers=count, version=importlib.metadata.version("sherpa-onnx"),
                    models=[file_hash(path) for path in models], min_duration_on=.2, min_duration_off=.2)
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    cache = cache_dir / f"speakers-{key}.json"
    if cache.is_file():
        try:
            segments = validate_segments(json.loads(cache.read_text())["segments"], duration)
            progress(duration)
            return segments
        except (ValueError, KeyError, TypeError, CensorError):
            pass
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(models[0])), num_threads=4),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(model=str(models[1]), num_threads=4),
        clustering=sherpa.FastClusteringConfig(num_clusters=count), min_duration_on=.2, min_duration_off=.2)
    if not config.validate():
        raise CensorError("Invalid local speaker model configuration.")
    with wave.open(str(audio)) as handle:
        if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (16000, 1, 2):
            raise CensorError("Speaker analysis requires mono 16 kHz PCM16 WAV.")
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768
    try:
        engine = sherpa.OfflineSpeakerDiarization(config)
        result = engine.process(samples, callback=lambda n, total: (progress(n / total * duration) or 0))
    except Exception as exc:
        raise CensorError(f"Speaker analysis failed: {exc}. Check the local speaker models.") from exc
    segments = validate_segments([dict(start=float(r.start), end=float(r.end), speaker=int(r.speaker))
                                  for r in result.sort_by_start_time()], duration)
    if save_cache:
        write_json(cache, dict(settings=settings, segments=segments))
    return segments


def overlap(start, end, segment):
    return max(0, min(end, segment["end"]) - max(start, segment["start"]))


def identify_reference(segments, start, end):
    votes = {}
    for segment in segments:
        votes[segment["speaker"]] = votes.get(segment["speaker"], 0) + overlap(start, end, segment)
    ranked = sorted(votes.items(), key=lambda pair: pair[1], reverse=True)
    total = sum(votes.values())
    if not ranked or total < 2:
        raise CensorError("Reference contains less than 2 seconds of detected speech; choose a longer solo segment.")
    speaker, seconds = ranked[0]
    purity = seconds / total
    if purity < .7:
        raise CensorError("Reference contains multiple prominent voices. Choose a clearer solo segment.")
    return speaker, dict(start=start, end=end, speaker_id=speaker, dominance=round(purity, 4),
                         detected_seconds=round(seconds, 3))


def label_words(words, segments, my_speaker):
    result = []
    for word in words:
        # Measure the union of each category, so overlapping diarization spans
        # cannot double-count coverage. Simultaneous me/others stays unknown.
        points = {word.start, word.end}
        relevant = [r for r in segments if overlap(word.start, word.end, r) > 0]
        for r in relevant:
            points.update((max(word.start, r["start"]), min(word.end, r["end"])))
        votes = {"me": 0., "others": 0., "unknown": 0.}
        boundaries = sorted(points)
        for lo, hi in zip(boundaries, boundaries[1:]):
            active = {"me" if r["speaker"] == my_speaker else "others"
                      for r in relevant if r["start"] < hi and r["end"] > lo}
            owner = next(iter(active)) if len(active) == 1 else "unknown"
            votes[owner] += hi - lo
        winner = max(votes, key=votes.get)
        coverage = votes[winner] / (word.end - word.start)
        label = winner if coverage >= .65 else "unknown"
        result.append(replace(word, speaker=label, speaker_coverage=round(coverage, 4)))
    return result


def cue_owners(words, ranges):
    """Keep the existing mute intervals and choose one cue for each interval."""
    owners = []
    for r in ranges:
        labels = {w.speaker or "unknown" for w in words
                  if w.profane and w.start < r.end and w.end > r.start}
        owners.append(next(iter(labels)) if len(labels) == 1 else "unknown")
    return owners
