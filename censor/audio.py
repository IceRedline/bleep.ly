"""Sample-accurate FFmpeg envelopes and censor sound mixing."""
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .ffmpeg import input_args, run, sound_duration
from .models import CensorRange, MediaInfo
from .utils import CensorError

RATE = 48000
FADE = .007


def samples(seconds: float) -> int:
    return round(seconds * RATE)


def gain_expression(ranges: list[CensorRange], mode: str, duck_db: float) -> str:
    if not ranges:
        return "1"
    floor = 0 if mode == "mute" else 10 ** (duck_db / 20)
    ramps = [f"max(0,min(1,min((t-({r.start - FADE:.9f}))/{FADE},"
             f"(({r.end + FADE:.9f})-t)/{FADE})))" for r in ranges]
    # Large left-associative sums exceed FFmpeg's expression parser depth.
    # A bounded tree also skips distant intervals during sample evaluation.
    def tree(start: int, end: int) -> str:
        if end - start == 1:
            return ramps[start]
        middle = (start + end) // 2
        lo = min(r.start for r in ranges[start:end]) - FADE
        hi = max(r.end for r in ranges[start:end]) + FADE
        return (f"if(between(t,{lo:.9f},{hi:.9f}),"
                f"({tree(start, middle)})+({tree(middle, end)}),0)")

    envelope = '+'.join(ramps) if len(ranges) <= 32 else tree(0, len(ranges))
    # Fade outside the padded interval: the entire interval remains fully muted.
    return f"1-({1 - floor:.12f})*min(1,({envelope}))"


def bed_filter(info: MediaInfo, ranges: list[CensorRange], mode: str, duck_db: float) -> str:
    return (f"aresample={RATE}:async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=end_sample={samples(info.duration)},asetpts=N/SR/TB,"
            f"aeval=exprs='val(ch)*({gain_expression(ranges, mode, duck_db)})':c=same")


def beep_filter(duration: float) -> str:
    count = max(1, samples(duration))
    fade = min(samples(FADE), count // 2)
    base = f"atrim=end_sample={count},asetpts=N/SR/TB"
    if fade:
        base += f",afade=t=in:ss=0:ns={fade},afade=t=out:ss={count - fade}:ns={fade}"
    return base


def prepare_sound(sound: Path, output: Path, duration: float) -> None:
    # Smooth the edges before fitting a single playback to each interval.
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(sound),
         "-map", "0:a:0", "-af", f"aresample={RATE},aformat=channel_layouts=stereo,{beep_filter(duration)}",
         "-c:a", "pcm_f32le", str(output)])


def filter_graph(info: MediaInfo, ranges: list[CensorRange], mode: str, duck_db: float,
                 source_duration: float, other_duration: float | None = None,
                 owners: list[str] | None = None) -> str:
    graph = [f"[0:{info.audio_index}]{bed_filter(info, ranges, mode, duck_db)}[bed]"]
    if other_duration is not None and (owners is None or len(owners) != len(ranges)):
        raise CensorError("Each censor interval requires a speaker label for two-sound rendering.")
    indices = [1 if other_duration is not None and owners[i] == "others" else 0 for i in range(len(ranges))]
    for slot in sorted(set(indices)):
        selected = [i for i, value in enumerate(indices) if value == slot]
        labels = "".join(f"[s{i}]" for i in selected)
        graph.append(f"[{slot + 1}:a:0]asplit={len(selected)}{labels}")
    for i, item in enumerate(ranges):
        # Cue duration is independent of the unchanged mute/duck interval.
        duration = other_duration if indices[i] else source_duration
        graph.append(f"[s{i}]{beep_filter(duration)},"
                     f"adelay={samples(item.start)}S:all=1[b{i}]")
    inputs = "[bed]" + "".join(f"[b{i}]" for i in range(len(ranges)))
    graph.append(f"{inputs}amix=inputs={len(ranges) + 1}:duration=first:normalize=0,"
                 # No global attenuation; limiter catches peaks without adding latency.
                 f"alimiter=limit=0.98:level=0:latency=1,atrim=end_sample={samples(info.duration)}[out]")
    return ";\n".join(graph)


@contextmanager
def new_output(path: Path):
    """Publish a complete output, never overwrite another file or keep partials."""
    if path.exists():
        raise CensorError(f"Output already exists: {path}. Choose another name.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bleep-ly-", dir=path.parent) as folder:
        staged = Path(folder) / path.name
        yield staged
        # Atomic no-clobber publication on the same filesystem.
        os.link(staged, path)


def render_video(source: Path, sound: Path, output: Path, info: MediaInfo,
                 ranges: list[CensorRange], mode: str, duck_db: float, work: Path,
                 progress: Callable[[float], None] | None = None,
                 other_sound: Path | None = None, owners: list[str] | None = None) -> None:
    graph = work / "mix.ffgraph"
    graph.write_text(filter_graph(info, ranges, mode, duck_db, sound_duration(sound),
                                 sound_duration(other_sound) if other_sound else None, owners), encoding="utf-8")
    with new_output(output) as staged:
        try:
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                 *input_args(source, info), "-i", str(sound),
                 *(["-i", str(other_sound)] if other_sound else []),
                 "-filter_complex_script", str(graph), "-map", f"0:{info.video_index}",
                 "-map", "[out]", "-map_metadata", "0", "-map_chapters", "0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(RATE),
                 "-avoid_negative_ts", "disabled", "-t", f"{info.duration:.9f}", str(staged)], progress)
        except CensorError as exc:
            raise CensorError(f"Video export failed; video was NOT re-encoded. "
                              f"The codec/container may not support stream copy; try --output result.mov "
                              f"or result.mkv.\n{exc}") from exc


def render_bed(source: Path, output: Path, info: MediaInfo, ranges: list[CensorRange],
               mode: str, duck_db: float, work: Path,
               progress: Callable[[float], None] | None = None) -> None:
    graph = work / "bed.ffgraph"
    graph.write_text(f"[0:{info.audio_index}]{bed_filter(info, ranges, mode, duck_db)}[out]", encoding="utf-8")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
         *input_args(source, info), "-filter_complex_script", str(graph), "-map", "[out]",
         "-c:a", "pcm_s24le", "-rf64", "auto", str(output)], progress)


def render_beep(sound: Path, output: Path) -> None:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
         "-i", str(sound), "-map", "0:a:0", "-af", beep_filter(sound_duration(sound)),
         "-c:a", "pcm_s24le", "-rf64", "auto", str(output)])
