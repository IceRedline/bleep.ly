"""JSON-lines bridge for the native app; reuse the CLI's inference and DSP.

Run `python -m censor.desktop REQUEST.json`. Stdout is a versioned event stream;
third-party diagnostics go to stderr. Requests and sessions belong to the app.
"""
import contextlib
import hashlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

from .audio import RATE, new_output, prepare_sound
from .stream_mix import cue_samples, render_track
from .ffmpeg import extract_audio, input_args, media_info, probe, require_tools, run, sound_duration
from .mlx_backend import MLXWhisperBackend, resolve_model
from .models import CensorRange
from .profanity import ProfanityMatcher
from .ranges import middle_ranges
from .transcription import (FasterWhisperBackend, cache_key, classify, load_cache,
                            parse_words, read_transcript, save_transcript)
from .utils import CensorError, finite_number
from .experimental_gpu import BACKENDS as GPU_BACKENDS, ExperimentalGPUBackend

# Approved beep_trimmed.wav timing, independent of the subsequently selected cue.
MUTE_CAP = 0.383021
PROTOCOL = 1
_protocol_output = None


def emit(event: str, *, _output=None, **payload):
    print(json.dumps({"version": PROTOCOL, "event": event, **payload}, ensure_ascii=False,
                     allow_nan=False), flush=True, file=_output if _output is not None else _protocol_output)


def progress(stage, duration):
    emit("progress", stage=stage, fraction=0, duration=duration)
    last = -1

    def update(seconds):
        nonlocal last
        percent = min(100, max(0, int(seconds / max(duration, .001) * 100)))
        if percent != last:
            last = percent
            emit("progress", stage=stage, fraction=percent / 100, duration=duration)
    return update


def fingerprint(source):
    stat = source.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def analyze(request):
    started = time.perf_counter()
    source = Path(request["source"]).resolve()
    if not source.is_file():
        raise CensorError(f"Input does not exist: {source}")
    signature = fingerprint(source)
    streams = [s for s in probe(source)["streams"] if s["codec_type"] == "audio"]
    selected = request.get("audio_stream")
    indices = list(range(len(streams))) if selected is None else [selected]
    if not indices:
        raise CensorError("Input has no audio track.")
    # A legacy unscoped transcript must never be copied onto unrelated audio.
    if request.get("transcript") and len(indices) > 1:
        raise CensorError("Select the audio track to receive this reviewed transcript.")
    infos = [media_info(source, index, allow_audio=True) for index in indices]
    duration = max(info.duration for info in infos)
    documents = []
    tracks = []
    for position, index in enumerate(indices):
        title = streams[index].get("tags", {}).get("title") or f"Track {index + 1}"
        tracks.append(dict(index=index, title=title))
        document = analyze_track({**request, "audio_stream": index, "_duration": duration,
                                  "_track_label": f"Track {position + 1}/{len(indices)} · " if len(indices) > 1 else ""})
        documents.append(document)
    if fingerprint(source) != signature:
        raise CensorError("Source changed during analysis. Open it again.")
    result = documents[0]
    result["words"] = [{**word, "audio_track": track["index"]}
                       for track, document in zip(tracks, documents) for word in document["words"]]
    result.update(tracks=tracks, audio_stream=selected, cache_hit=all(d["cache_hit"] for d in documents),
                  analysis_seconds=time.perf_counter() - started)
    return result


def analyze_track(request):
    started = time.perf_counter()
    language = request.get("language", "ru")
    if language not in {"ru", "en"}:
        raise CensorError("Choose Russian or English for the media language.")
    cache_hit = False
    recognition_seconds = None
    backend = "reviewed-transcript"
    style = request.get("censor_style", "middle")
    if style not in {"middle", "full"}:
        raise CensorError("Choose middle or full word censoring.")
    source = Path(request["source"]).resolve()
    stream = request.get("audio_stream")
    info = media_info(source, stream, allow_audio=True)
    info = replace(info, duration=request.get("_duration", info.duration))
    prefix = request.get("_track_label", "")
    protocol_output = sys.stdout
    def report(label, fraction):
        emit("progress", stage=prefix + label, fraction=fraction, duration=info.duration, _output=protocol_output)
    def tracking(label, length):
        return progress(prefix + label, length)
    signature = fingerprint(source)
    if request.get("transcript"):
        words = read_transcript(Path(request["transcript"]), info.duration)
    else:
        try:
            matcher = ProfanityMatcher.from_request(language, request.get("word_lists"))
        except ValueError as exc:
            raise CensorError(f"Invalid word lists: {exc}") from exc
        backend = request.get("backend", "faster-whisper")
        if backend not in {"mlx", "faster-whisper", "whisperkit"} | GPU_BACKENDS:
            raise CensorError("Unknown speech backend.")
        model = request.get("model", "large-v3-turbo")
        compute = "float16" if backend == "mlx" else "int8"
        if backend == "mlx":
            model = resolve_model(model)
        if backend in GPU_BACKENDS:
            from .experimental_gpu import MODELS, prepare, cache_identity as gpu_cache_identity
            if model not in MODELS or MODELS[model][0] != backend:
                raise CensorError("Selected experimental model does not match its GPU backend.")
            if model == "gigaam-v3" and language != "ru":
                raise CensorError("GigaAM v3 supports Russian only. Choose Whisper for English.")
            report("Preparing speech model", 0)
            assets = prepare(model, offline=request.get("offline", True), progress=report)
            native_engine = ExperimentalGPUBackend(model, assets, language=language,
                                                    stage=lambda label: report(label, 0))
            key, metadata = gpu_cache_identity(source, model, info.audio_index,
                                               tracking("Reading media", source.stat().st_size), language=language)
        elif backend == "whisperkit":
            from .whisperkit_backend import WhisperKitBackend, prepare_assets, cache_identity
            model_folder = Path(request["whisperkit_model_folder"]).resolve()
            executable = Path(request["whisperkit_executable"]).resolve()
            native_engine = WhisperKitBackend(executable, model_folder,
                stage=lambda label: report(label, 0), language=language)
            report("Preparing WhisperKit model", 0)
            prepare_assets(model_folder, offline=request.get("offline", True),
                           progress=report)
            key, metadata = cache_identity(source, model_folder, executable, info.audio_index,
                                          tracking("Reading media", source.stat().st_size), language=language)
        else:
            key, metadata = cache_key(source, model, language, compute, info.audio_index,
                                      tracking("Reading media", source.stat().st_size), backend=backend)
        if "app_cache_identity" in request:
            identity = request["app_cache_identity"]
            if not isinstance(identity, str) or not identity:
                raise CensorError("Invalid app recognition cache identity.")
            metadata["app_cache_identity"] = identity
            # All recognizers share the same build/installation boundary. Legacy
            # CLI/benchmark caches remain available only to unscoped requests.
            key = hashlib.sha256(json.dumps([key, identity]).encode()).hexdigest()
        cache = Path(request["cache_dir"]) / f"{key}.json"
        words = None if request.get("bypass_cache", False) else load_cache(cache, info.duration)
        cache_hit = words is not None
        if cache_hit and request.get("managed_cache"):
            try:
                os.utime(cache, None)
            except OSError:
                pass
        if words is None:
            with tempfile.TemporaryDirectory(prefix="bleep-speech-") as folder:
                audio = Path(folder) / "speech.wav"
                extract_audio(source, audio, info, tracking("Preparing audio", info.duration))
                callback = tracking("Recognizing speech", info.duration)
                protocol_output = sys.stdout
                def inference_progress(seconds):
                    # Library stdout is redirected, but app progress must stay on the protocol pipe.
                    with contextlib.redirect_stdout(protocol_output):
                        callback(seconds)
                engine = MLXWhisperBackend if backend == "mlx" else FasterWhisperBackend
                # Some inference libraries print to stdout; keep the protocol clean.
                with contextlib.redirect_stdout(sys.stderr):
                    transcriber = native_engine if backend == "whisperkit" or backend in GPU_BACKENDS else engine(model, language, compute, request.get("offline", True))
                    recognition_started = time.perf_counter()
                    raw = transcriber.transcribe(audio, inference_progress)
                    recognition_seconds = time.perf_counter() - recognition_started
                if backend == "whisperkit" or backend in GPU_BACKENDS:
                    metadata["native_metrics"] = native_engine.metrics
                words = parse_words({"words": [asdict(w) for w in raw
                                               if w.word.strip() and w.end > w.start and w.start < info.duration]}, info.duration)
                if cache.resolve() == source:
                    raise CensorError("Cache collides with source.")
                save_transcript(cache, words, metadata)
        words = classify(words, matcher)
    if fingerprint(source) != signature:
        raise CensorError("Source changed during analysis. Open it again.")
    if backend != "reviewed-transcript":
        from .recognition_history import record_run
        try:
            # Preserve the cache's full identity/metrics even when no inference ran.
            cached_metadata = json.loads(cache.read_text())["metadata"]
            record_run(request.get("history_dir", Path(request["cache_dir"]).parent / "recognition-history"),
                       metadata={**cached_metadata, "detection_language": language,
                                 "profanity_rules": matcher.rules, "matcher_sha256": matcher.identity()},
                       words=[asdict(word) for word in words],
                       cache_path=cache, source=source, duration=info.duration,
                       analysis_seconds=time.perf_counter() - started,
                       recognition_seconds=recognition_seconds, cache_hit=cache_hit)
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).exception("Could not save recognition history; analysis remains available")
    items = []
    for word in words:
        interval = (CensorRange(word.start, word.end) if style == "full" else
                    middle_ranges([replace(word, profane=True)], info.duration, MUTE_CAP)[0])
        items.append({**asdict(word), "mute_start": interval.start, "mute_end": interval.end})
    return {"source": str(source), "fingerprint": signature, "duration": info.duration,
            "has_video": info.video_index >= 0, "audio_stream": stream,
            "audio_count": info.audio_count, "censor_style": style, "words": items,
            "language": language, "engine": backend, "cache_hit": cache_hit, "analysis_seconds": time.perf_counter() - started}


def reviewed_ranges(document, duration):
    # Validate words but retain their pairing with explicit mute boundaries.
    parse_words(document, duration, require_flags=True)
    ranges = []
    for item in document["words"]:
        start = finite_number(item.get("mute_start"), "mute_start")
        end = finite_number(item.get("mute_end"), "mute_end")
        if not 0 <= start < end <= duration:
            raise CensorError("Mute interval must satisfy 0 <= start < end <= duration.")
        if item["profane"]:
            ranges.append(CensorRange(start, end))
    # Union overlaps without altering either outer boundary. One cue per interval.
    merged = []
    for interval in sorted(ranges):
        if merged and interval.start <= merged[-1].end:
            merged[-1] = CensorRange(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


def export(request):
    document = request["document"]
    source = Path(document["source"]).resolve()
    output = Path(request["output"]).resolve()
    tracks = document.get("tracks") or [{"index": document.get("audio_stream") or 0, "title": "Audio"}]
    indices = [track["index"] for track in tracks]
    if any(not isinstance(index, int) or isinstance(index, bool) for index in indices) or len(set(indices)) != len(indices):
        raise CensorError("Invalid review audio tracks.")
    infos = [media_info(source, index, allow_audio=True) for index in indices]
    duration = max(info.duration for info in infos)
    infos = [replace(info, duration=duration) for info in infos]
    info = infos[0]
    if fingerprint(source) != document["fingerprint"]:
        raise CensorError("Source changed since analysis. Open it again before exporting.")
    kind = request["format"]
    if kind not in {"audio", "video"}:
        raise CensorError("Choose Audio Only or Video.")
    if kind == "video" and (info.video_index < 0 or output.suffix.lower() not in {".mov", ".mp4", ".mkv"}):
        raise CensorError("Video export requires a video source and .mov, .mp4 or .mkv destination.")
    if kind == "audio" and output.suffix.lower() != ".wav":
        raise CensorError("Audio Only exports a 48 kHz, 24-bit stereo WAV.")
    sound_type = request.get("sound", "beep")
    if sound_type not in {"beep", "silence", "custom"}:
        raise CensorError("Unknown censor sound.")
    custom = Path(request["custom_sound"]).resolve() if sound_type == "custom" else None
    if output in {source, custom} or output.exists():
        raise CensorError("Choose a new output name; existing files are never overwritten.")
    if any(word.get("audio_track", indices[0]) not in indices for word in document["words"]):
        raise CensorError("A review word refers to an unknown audio track.")
    track_ranges = [reviewed_ranges({"words": [w for w in document["words"]
                      if w.get("audio_track", indices[0]) == index]}, duration) for index in indices]
    ranges = [interval for values in track_ranges for interval in values]
    with tempfile.TemporaryDirectory(prefix="bleep-export-") as folder:
        work = Path(folder)
        cue = None
        if ranges and sound_type != "silence":
            cue = work / "cue.wav"
            if custom:
                prepare_sound(custom, cue, sound_duration(custom))
            else:
                raw = work / "beep.wav"
                run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                     f"sine=frequency=1000:sample_rate={RATE}:duration={MUTE_CAP}", str(raw)])
                prepare_sound(raw, cue, MUTE_CAP)
        with cue_samples(cue, work) as cue_pcm:
            if kind == "audio" and len(infos) == 1:
                with new_output(output) as staged:
                    render_track(source, staged, info, track_ranges[0], cue_pcm,
                                 progress("Exporting audio", duration))
            else:
                # Preserve float precision until the final mix/encode. Each track
                # uses a constant-size mixer, independent of the number of words.
                update = progress("Exporting video" if kind == "video" else "Exporting audio",
                                  duration * (len(infos) + 1))
                prepared = []
                for i, (track_info, values) in enumerate(zip(infos, track_ranges)):
                    track = work / f"track-{i}.wav"
                    render_track(source, track, track_info, values, cue_pcm,
                                 lambda seconds, i=i: update(i * duration + seconds), floating=True)
                    prepared.append(track)
                inputs = [arg for track in prepared for arg in ("-i", str(track))]
                if kind == "audio":
                    graph = ''.join(f'[{i + 1}:a:0]' for i in range(len(prepared)))
                    graph += f'amix=inputs={len(prepared)}:duration=longest:normalize=1[out]'
                    audio_maps = ["-filter_complex", graph, "-map", "[out]"]
                else:
                    audio_maps = [arg for i in range(len(prepared)) for arg in ('-map', f'{i + 1}:a:0')]
                metadata = ([arg for i, index in enumerate(indices) for arg in
                             (f'-map_metadata:s:a:{i}', f'0:s:a:{index}')]
                            if kind == 'video' else [])
                with new_output(output) as staged:
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                         *input_args(source, info), *inputs,
                         *(["-map", f"0:{info.video_index}", "-c:v", "copy"] if kind == "video" else []),
                         *audio_maps, "-map_metadata", "0", *metadata,
                         *(["-c:a", "aac", "-b:a", "320k", "-avoid_negative_ts", "disabled"] if kind == "video"
                           else ["-c:a", "pcm_s24le", "-rf64", "auto"]),
                         "-ar", str(RATE), "-t", f"{duration:.9f}", str(staged)],
                        lambda seconds: update(len(infos) * duration + seconds))
    return {"output": str(output)}


def main():
    from .cache_policy import lease
    with lease(tempfile.gettempdir()):
        return _main()


def _main():
    # The app cancels this process group, including ffmpeg workers.
    if os.getpgrp() != os.getpid():
        os.setsid()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    # Keep a dedicated protocol stream even while third-party stdout is redirected.
    # Use the same emitter as direct calls so stream arguments cannot enter JSON.
    global _protocol_output
    previous_output = _protocol_output
    _protocol_output = sys.stdout
    request = {}
    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        require_tools()
        operation = request["operation"]
        if operation not in {"analyze", "export", "preview"}:
            raise CensorError("Unsupported desktop operation.")
        if operation == "preview":
            from .preview import preview
            result = preview(request)
        else:
            if operation == "analyze":
                from .cache_policy import recognition_cache
                with recognition_cache(request):
                    result = analyze(request)
            else:
                result = export(request)
        emit("result", **result)
        return 0
    except KeyboardInterrupt:
        emit("cancelled")
        return 130
    except Exception as exc:
        from .model_downloads import requires_model_download
        if (isinstance(request, dict) and request.get("operation") == "analyze" and request.get("offline", True)
                and requires_model_download(exc)):
            emit("error", code="model_download_required",
                 message="The selected model is not downloaded. Allow model downloads in Settings, "
                         "then open your file again. Your recordings stay on your Mac.")
        else:
            emit("error", message=str(exc))
        return 1
    finally:
        _protocol_output = previous_output


if __name__ == "__main__":
    sys.exit(main())
