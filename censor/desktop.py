"""JSON-lines bridge for the native app; reuse the CLI's inference and DSP.

Run `python -m censor.desktop REQUEST.json`. Stdout is a versioned event stream;
third-party diagnostics go to stderr. Requests and sessions belong to the app.
"""
import contextlib
import json
import os
import signal
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

from .audio import (RATE, bed_filter, filter_graph, new_output, prepare_sound)
from .ffmpeg import extract_audio, input_args, media_info, require_tools, run, sound_duration
from .mlx_backend import MLXWhisperBackend, resolve_model
from .models import CensorRange
from .profanity import ProfanityMatcher
from .ranges import middle_ranges
from .transcription import (FasterWhisperBackend, cache_key, classify, load_cache,
                            parse_words, read_transcript, save_transcript)
from .utils import CensorError, finite_number

# Approved beep_trimmed.wav timing, independent of the subsequently selected cue.
MUTE_CAP = 0.383021
PROTOCOL = 1


def emit(event: str, **payload):
    print(json.dumps({"version": PROTOCOL, "event": event, **payload}, ensure_ascii=False,
                     allow_nan=False), flush=True)


def progress(stage, duration):
    emit("progress", stage=stage, fraction=0)
    last = -1

    def update(seconds):
        nonlocal last
        percent = min(100, max(0, int(seconds / max(duration, .001) * 100)))
        if percent != last:
            last = percent
            emit("progress", stage=stage, fraction=percent / 100)
    return update


def fingerprint(source):
    stat = source.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def analyze(request):
    started = time.perf_counter()
    cache_hit = False
    backend = "reviewed-transcript"
    style = request.get("censor_style", "middle")
    if style not in {"middle", "full"}:
        raise CensorError("Choose middle or full word censoring.")
    source = Path(request["source"]).resolve()
    stream = request.get("audio_stream")
    info = media_info(source, stream, allow_audio=True)
    signature = fingerprint(source)
    if request.get("transcript"):
        words = read_transcript(Path(request["transcript"]), info.duration)
    else:
        backend = request.get("backend", "faster-whisper")
        if backend not in {"mlx", "faster-whisper", "whisperkit"}:
            raise CensorError("Unknown speech backend.")
        model = request.get("model", "large-v3-turbo")
        compute = "float16" if backend == "mlx" else "int8"
        if backend == "mlx":
            model = resolve_model(model)
        if backend == "whisperkit":
            from .whisperkit_backend import WhisperKitBackend, prepare_assets, cache_identity
            model_folder = Path(request["whisperkit_model_folder"]).resolve()
            executable = Path(request["whisperkit_executable"]).resolve()
            native_engine = WhisperKitBackend(executable, model_folder,
                stage=lambda label: emit("progress", stage=label, fraction=0))
            emit("progress", stage="Preparing WhisperKit model", fraction=0)
            prepare_assets(model_folder, offline=request.get("offline", True))
            key, metadata = cache_identity(source, model_folder, executable, info.audio_index,
                                          progress("Reading media", source.stat().st_size))
        else:
            key, metadata = cache_key(source, model, "ru", compute, info.audio_index,
                                      progress("Reading media", source.stat().st_size), backend=backend)
        cache = Path(request["cache_dir"]) / f"{key}.json"
        words = None if request.get("bypass_cache", False) else load_cache(cache, info.duration)
        cache_hit = words is not None
        if words is None:
            with tempfile.TemporaryDirectory(prefix="bleep-speech-") as folder:
                audio = Path(folder) / "speech.wav"
                extract_audio(source, audio, info, progress("Preparing audio", info.duration))
                callback = progress("Recognizing speech", info.duration)
                engine = MLXWhisperBackend if backend == "mlx" else FasterWhisperBackend
                # Some inference libraries print to stdout; keep the protocol clean.
                with contextlib.redirect_stdout(sys.stderr):
                    transcriber = native_engine if backend == "whisperkit" else engine(model, "ru", compute, request.get("offline", True))
                    raw = transcriber.transcribe(audio, callback)
                if backend == "whisperkit":
                    metadata["native_metrics"] = native_engine.metrics
                words = parse_words({"words": [asdict(w) for w in raw
                                               if w.word.strip() and w.end > w.start and w.start < info.duration]}, info.duration)
                if cache.resolve() == source:
                    raise CensorError("Cache collides with source.")
                save_transcript(cache, words, metadata)
        words = classify(words, ProfanityMatcher.from_file(Path(__file__).resolve().parents[1] / "profanity.txt"))
    if fingerprint(source) != signature:
        raise CensorError("Source changed during analysis. Open it again.")
    items = []
    for word in words:
        interval = (CensorRange(word.start, word.end) if style == "full" else
                    middle_ranges([replace(word, profane=True)], info.duration, MUTE_CAP)[0])
        items.append({**asdict(word), "mute_start": interval.start, "mute_end": interval.end})
    return {"source": str(source), "fingerprint": signature, "duration": info.duration,
            "has_video": info.video_index >= 0, "audio_stream": stream,
            "audio_count": info.audio_count, "censor_style": style, "words": items,
            "engine": backend, "cache_hit": cache_hit, "analysis_seconds": time.perf_counter() - started}


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
    info = media_info(source, document.get("audio_stream"), allow_audio=True)
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
    ranges = reviewed_ranges(document, info.duration)
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
        graph = work / "mix.ffgraph"
        graph.write_text(filter_graph(info, ranges, "mute", -30, sound_duration(cue)) if cue else
                         f"[0:{info.audio_index}]{bed_filter(info, ranges, 'mute', -30)}[out]")
        with new_output(output) as staged:
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                 *input_args(source, info), *(["-i", str(cue)] if cue else []),
                 "-filter_complex_script", str(graph),
                 *(["-map", f"0:{info.video_index}", "-c:v", "copy"] if kind == "video" else []),
                 "-map", "[out]", "-map_metadata", "0",
                 *(["-c:a", "aac", "-b:a", "320k", "-avoid_negative_ts", "disabled"] if kind == "video"
                   else ["-c:a", "pcm_s24le", "-rf64", "auto"]),
                 "-ar", str(RATE), "-t", f"{info.duration:.9f}", str(staged)],
                progress("Exporting video" if kind == "video" else "Exporting audio", info.duration))
    return {"output": str(output)}


def main():
    # The app cancels this process group, including ffmpeg workers.
    if os.getpgrp() != os.getpid():
        os.setsid()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    # Keep a dedicated protocol stream even while third-party stdout is redirected.
    global emit
    protocol_output = sys.stdout
    def emit(event, **payload):
        print(json.dumps({"version": PROTOCOL, "event": event, **payload}, ensure_ascii=False,
                         allow_nan=False), file=protocol_output, flush=True)
    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        require_tools()
        operation = request["operation"]
        if operation not in {"analyze", "export"}:
            raise CensorError("Unsupported desktop operation.")
        result = analyze(request) if operation == "analyze" else export(request)
        emit("result", **result)
        return 0
    except KeyboardInterrupt:
        emit("cancelled")
        return 130
    except Exception as exc:
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
