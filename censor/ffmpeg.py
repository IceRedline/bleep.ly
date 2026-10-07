import json
import logging
import math
import re
import shlex
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .models import MediaInfo
from .utils import CensorError

LOG = logging.getLogger(__name__)


def require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise CensorError(f"{tool} is not installed. On macOS: brew install ffmpeg")


def run(args: list[str]) -> str:
    LOG.debug("%s", shlex.join(args))
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise CensorError(f"{args[0]} is not installed. On macOS: brew install ffmpeg") from exc
    if result.returncode:
        raise CensorError(f"{args[0]} failed:\n{result.stderr[-5000:].strip()}")
    return result.stdout


def probe(path: Path) -> dict:
    if not path.is_file():
        raise CensorError(f"File does not exist: {path}")
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def timecode_seconds(code: str, fps: Fraction) -> Fraction:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})", code)
    if not match:
        raise CensorError(f"Unsupported source timecode: {code!r}")
    hours, minutes, seconds, sep, frames = match.groups()
    h, m, s, f = map(int, (hours, minutes, seconds, frames))
    nominal = round(fps)
    if m >= 60 or s >= 60 or f >= nominal:
        raise CensorError(f"Invalid source timecode: {code!r}")
    count = ((h * 60 + m) * 60 + s) * nominal + f
    if sep == ";":
        if fps not in (Fraction(30000, 1001), Fraction(60000, 1001)):
            raise CensorError("Drop-frame timecode requires 29.97 or 59.94 fps.")
        drop = 2 if nominal == 30 else 4
        total_minutes = h * 60 + m
        count -= drop * (total_minutes - total_minutes // 10)
    return Fraction(count, 1) / fps


def media_info(path: Path, audio_stream: int | None = None) -> MediaInfo:
    data = probe(path)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    if video is None:
        raise CensorError("Input has no video stream.")
    if not audio:
        raise CensorError("Input has no audio track.")
    if len(audio) > 1 and audio_stream is None:
        raise CensorError(f"Input has {len(audio)} audio tracks. Select --audio-stream 0 (or another index). "
                          "Only the selected track will be included in the output.")
    index = audio_stream if audio_stream is not None else 0
    if not 0 <= index < len(audio):
        raise CensorError(f"--audio-stream must be between 0 and {len(audio) - 1}.")
    try:
        start = float(video.get("start_time", data.get("format", {}).get("start_time", 0)))
        duration = float(video.get("duration") or data["format"]["duration"])
        fps = Fraction(video.get("avg_frame_rate", "0/1"))
        if fps <= 0:
            fps = Fraction(video["r_frame_rate"])
        if not math.isfinite(duration) or duration <= 0 or not math.isfinite(start) or fps <= 0:
            raise ValueError
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise CensorError("Cannot determine a finite video duration/frame rate.") from exc
    code = video.get("tags", {}).get("timecode") or data.get("format", {}).get("tags", {}).get("timecode")
    color = {"bt709": "1-1-1 (Rec. 709)", "smpte2084": "9-16-9 (Rec. 2020 PQ)",
             "arib-std-b67": "9-18-9 (Rec. 2020 HLG)"}.get(video.get("color_transfer"))
    return MediaInfo(duration, video["index"], audio[index]["index"], len(audio),
                     video["width"], video["height"], fps, start,
                     timecode_seconds(code, fps) if code else Fraction(0), color)


def sound_duration(path: Path) -> float:
    data = probe(path)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if audio is None:
        raise CensorError("Censor sound has no audio track.")
    try:
        duration = float(audio.get("duration") or data["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (ValueError, KeyError) as exc:
        raise CensorError("Censor sound must have a known, positive duration.") from exc


def input_args(path: Path, info: MediaInfo) -> list[str]:
    # Preserve A/V offsets, then express all audio times from first video frame.
    return ["-copyts", "-itsoffset", f"{-info.start:.9f}", "-i", str(path)]


def extract_audio(path: Path, output: Path, info: MediaInfo) -> None:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
         *input_args(path, info), "-map", f"0:{info.audio_index}", "-vn",
         "-af", "aresample=16000:async=1:first_pts=0,apad",
         "-t", f"{info.duration:.9f}", "-ac", "1", "-c:a", "pcm_s16le", str(output)])
