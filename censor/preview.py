"""Immutable preview snapshots with small, sample-aligned audio patches."""
import ctypes
import fcntl
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from .audio import FADE, RATE, bed_filter, filter_graph, new_output, prepare_sound, samples
from .ffmpeg import input_args, media_info, run, sound_duration
from .models import CensorRange
from .utils import CensorError

# FFmpeg's limiter has 5 ms lookahead and 50 ms release. Keep its settling
# region outside the patch, including after removing an overlapping cue.
SETTLE = .25
VERSION = 1


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _clone(source, destination):
    # APFS copy-on-write keeps a 30-minute snapshot cheap and never modifies
    # audio that AVPlayer or Undo may still be using. Other filesystems copy.
    if sys.platform == "darwin":
        clone = ctypes.CDLL(None, use_errno=True).clonefile
        clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clone.restype = ctypes.c_int
        if clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
            return
    shutil.copyfile(source, destination)


def _wav_data(path):
    """Locate stereo PCM24 samples, including FFmpeg extensible WAV/RF64."""
    with path.open("rb") as file:
        header = file.read(12)
        if header[:4] not in (b"RIFF", b"RF64") or header[8:] != b"WAVE":
            raise CensorError("Invalid preview WAV.")
        data_size = None
        valid_format = False
        while chunk := file.read(8):
            if len(chunk) != 8:
                break
            name, length = struct.unpack("<4sI", chunk)
            if name == b"ds64":
                payload = file.read(length)
                data_size = struct.unpack_from("<Q", payload, 8)[0]
            elif name == b"fmt ":
                payload = file.read(length)
                tag, channels, rate, _, block, bits = struct.unpack_from("<HHIIHH", payload)
                pcm = tag == 1 or (tag == 65534 and len(payload) >= 40 and
                                  payload[24:40] == bytes.fromhex("0100000000001000800000aa00389b71"))
                valid_format = pcm and (channels, rate, block, bits) == (2, RATE, 6, 24)
            elif name == b"data":
                size = data_size if length == 0xffffffff else length
                if valid_format and size is not None and size % 6 == 0 and file.tell() + size <= path.stat().st_size:
                    return file.tell(), size // 6
                break
            else:
                file.seek(length, 1)
            if length % 2:
                file.seek(1, 1)
    raise CensorError("Preview must contain complete 48 kHz stereo PCM24 audio.")


def _regions(old, new, duration, cue_duration):
    changed = set(old).symmetric_difference(new)
    regions = []
    for interval in sorted(changed):
        start = max(0, math.floor((interval.start - FADE - SETTLE) * RATE))
        end = min(samples(duration), math.ceil((max(interval.end + FADE, interval.start + cue_duration) + SETTLE) * RATE))
        if regions and start <= regions[-1][1] + samples(SETTLE):
            regions[-1] = (regions[-1][0], max(regions[-1][1], end))
        else:
            regions.append((start, end))
    return regions


def preview(request):
    from .cache_policy import preview_worker
    with preview_worker(request):
        return _preview(request)


def _preview(request):
    # Import here because desktop dispatches this operation after initialization.
    from .desktop import MUTE_CAP, emit, fingerprint, reviewed_ranges

    document = request["document"]
    source = Path(document["source"]).resolve()
    output = Path(request["output"]).resolve()
    tracks = document.get("tracks") or [{"index": document.get("audio_stream") or 0}]
    if len(tracks) != 1 or type(tracks[0]["index"]) is not int:
        raise CensorError("Preview requires one audio track.")
    index = tracks[0]["index"]
    info = media_info(source, index, allow_audio=True)
    if fingerprint(source) != document["fingerprint"]:
        raise CensorError("Source changed since analysis. Open it again before previewing.")
    if any(word.get("audio_track", index) != index for word in document["words"]):
        raise CensorError("A review word refers to an unknown audio track.")
    ranges = reviewed_ranges(document, info.duration)
    mode = request.get("sound", "beep")
    if mode not in {"beep", "silence", "custom"}:
        raise CensorError("Unknown censor sound.")
    custom = Path(request["custom_sound"]).resolve() if mode == "custom" else None
    if output in {source, custom} or output.exists() or output.suffix.lower() != ".wav":
        raise CensorError("Choose a new WAV preview destination.")
    identity = dict(version=VERSION, source=str(source), fingerprint=fingerprint(source),
                    track=index, duration=info.duration)
    cache = Path(request["preview_cache"]) / _key(identity)
    cache.mkdir(parents=True, exist_ok=True)
    pcm = cache / "source.wav"
    cue_identity = [str(custom), fingerprint(custom)] if custom else mode
    identity["sound"] = cue_identity
    cue = None
    cue_duration = 0
    decoded = False
    if request.get("managed_cache"):
        from .cache_policy import reserve_preview
        session = Path(request["preview_cache"]).parent
        # Budget the largest possible patch as well as new decoded/base/output WAVs.
        # Counting logical bytes is conservative on APFS, where snapshots share blocks.
        frames = samples(info.duration)
        missing_source = 0 if pcm.exists() else frames * 8 + 4096
        has_cue = mode != "silence" and bool(ranges)
        base_path = cache / ("limited.wav" if has_cue else "plain.wav")
        missing_base = 0 if base_path.exists() else frames * 6 + 4096
        cue_bytes = samples(sound_duration(custom) if custom else MUTE_CAP) * 8 + 4096 if has_cue else 0
        protected = {cache, output.parent}
        for name in ("previous_output", "playing_output"):
            if request.get(name):
                protected.add(Path(request[name]).parent)
        reserve_preview(session, protected, missing_source + missing_base + frames * 12 + cue_bytes + 65536)
    emit("progress", stage="Preparing preview audio", fraction=0)
    # Cancellation releases flock automatically. A replacement request can reuse
    # completed assets, but never see half-written source/cue files.
    with (cache / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not pcm.exists():
            with new_output(pcm) as staged:
                run(["ffmpeg", "-v", "error", "-nostdin", "-n", *input_args(source, info),
                     "-map", f"0:{info.audio_index}", "-af", bed_filter(info, [], "mute", -30),
                     "-c:a", "pcm_f32le", "-rf64", "auto", str(staged)])
            decoded = True
        if mode != "silence" and ranges:
            cue = cache / f"cue-{_key(cue_identity)}.wav"
            if not cue.exists():
                with tempfile.TemporaryDirectory(dir=cache) as folder:
                    raw = Path(folder) / "beep.wav"
                    if custom is None:
                        run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                             f"sine=frequency=1000:sample_rate={RATE}:duration={MUTE_CAP}", str(raw)])
                    with new_output(cue) as staged:
                        prepare_sound(custom or raw, staged, sound_duration(custom) if custom else MUTE_CAP)
            cue_duration = sound_duration(cue)
        baseline = cache / ("limited.wav" if cue else "plain.wav")
        if not baseline.exists():
            with new_output(baseline) as staged:
                run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(pcm),
                     *(["-af", "alimiter=limit=0.98:level=0:latency=1"] if cue else []),
                     "-c:a", "pcm_s24le", "-rf64", "auto", str(staged)])

    previous = Path(request["previous_output"]) if request.get("previous_output") else None
    old_ranges = []
    base = baseline
    if previous and previous.is_file():
        try:
            old = json.loads(previous.with_suffix(".json").read_text())
            # Limiter is globally enabled only when a non-silent cue is present,
            # matching export. Crossing zero intervals switches to the baseline.
            if old["identity"] == identity and old["limited"] == bool(cue):
                if _wav_data(previous)[1] == samples(info.duration):
                    old_ranges = [CensorRange(*value) for value in old["ranges"]]
                    base = previous
        except (OSError, ValueError, KeyError, TypeError, CensorError):
            pass
    regions = _regions(old_ranges, ranges, info.duration, cue_duration)
    rendered_seconds = 0
    with new_output(output) as staged, tempfile.TemporaryDirectory(prefix="bleep-patch-") as folder:
        _clone(base, staged)
        offset, frames = _wav_data(staged)
        if frames != samples(info.duration):
            raise CensorError("Preview duration does not match the source.")
        with staged.open("r+b") as destination:
            for number, (start, end) in enumerate(regions):
                render_start = max(0, start - samples(SETTLE))
                render_end = min(frames, end + samples(SETTLE))
                origin = render_start / RATE
                window = replace(info, start=0, audio_index=0, duration=(render_end - render_start) / RATE)
                selected = [CensorRange(item.start - origin, item.end - origin) for item in ranges
                            if item.start - FADE < render_end / RATE and
                            max(item.end + FADE, item.start + cue_duration) > origin]
                graph = (filter_graph(window, selected, "mute", -30, cue_duration) if cue else
                         f"[0:0]{bed_filter(window, selected, 'mute', -30)}[out]")
                script = Path(folder) / "patch.ffgraph"
                script.write_text(graph)
                patch = Path(folder) / f"patch-{number}.wav"
                run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-ss", f"{origin:.9f}",
                     "-i", str(pcm), *(["-i", str(cue)] if cue else []),
                     "-filter_complex_script", str(script), "-map", "[out]", "-c:a", "pcm_s24le", str(patch)])
                patch_offset, patch_frames = _wav_data(patch)
                skip = start - render_start
                if patch_frames < skip + end - start:
                    raise CensorError("Incomplete preview patch.")
                with patch.open("rb") as audio:
                    audio.seek(patch_offset + skip * 6)
                    destination.seek(offset + start * 6)
                    remaining = (end - start) * 6
                    while remaining:
                        data = audio.read(min(remaining, 1024 * 1024))
                        if not data:
                            raise CensorError("Incomplete preview patch.")
                        destination.write(data)
                        remaining -= len(data)
                patch.unlink()
                rendered_seconds += window.duration
                emit("progress", stage="Updating preview", fraction=(number + 1) / len(regions))
        metadata = dict(identity=identity, limited=bool(cue), ranges=[[r.start, r.end] for r in ranges],
                        rendered_seconds=rendered_seconds, source_decoded=decoded)
        output.with_suffix(".json").write_text(json.dumps(metadata))
    return dict(output=str(output), rendered_seconds=rendered_seconds, patches=len(regions), source_decoded=decoded)
