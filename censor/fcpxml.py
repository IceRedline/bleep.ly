"""FCPXML 1.10 interchange using documented Apple elements."""
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from .audio import RATE, new_output, render_bed, render_beep, samples
from .ffmpeg import sound_duration
from .models import CensorRange, MediaInfo
from .utils import CensorError


def rational_time(seconds: float | Fraction, rate: int = RATE) -> str:
    value = seconds if isinstance(seconds, Fraction) else Fraction(round(seconds * rate), rate)
    return f"{value.numerator}/{value.denominator}s"


def build_xml(source: Path, info: MediaInfo, media_dir: Path, ranges: list[CensorRange],
              cue_duration: float) -> ET.ElementTree:
    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    attrs = dict(id="r1", frameDuration=rational_time(1 / info.fps),
                 width=str(info.width), height=str(info.height))
    if info.color_space:
        attrs["colorSpace"] = info.color_space
    ET.SubElement(resources, "format", attrs)
    # Storyline boundaries must be on frames, audio offsets remain sample-accurate.
    frame_count = max(1, math.floor(Fraction(str(info.duration)) * info.fps + Fraction(1, 1000)))
    duration = Fraction(frame_count, 1) / info.fps
    if any(Fraction(samples(r.end), RATE) > duration for r in ranges):
        raise CensorError("A censor interval extends beyond the last complete video frame. "
                          "Trim that transcript timestamp or use video export (VFR sources need conforming for FCPXML).")
    video = ET.SubElement(resources, "asset", id="r2", name=source.name,
                  start=rational_time(info.timecode), duration=rational_time(duration),
                  hasVideo="1", hasAudio="1", format="r1")
    ET.SubElement(video, "media-rep", kind="original-media", src=source.resolve().as_uri())
    bed = ET.SubElement(resources, "asset", id="r3", name="Censored original audio", start="0s",
                  duration=rational_time(info.duration), hasAudio="1", audioSources="1", audioChannels="2", audioRate=str(RATE))
    ET.SubElement(bed, "media-rep", kind="original-media", src=(media_dir / "original_censored.wav").resolve().as_uri())
    for i, item in enumerate(ranges):
        beep = ET.SubElement(resources, "asset", id=f"r{i + 4}", name=f"BEEP {i + 1:03d}", start="0s",
                      duration=rational_time(cue_duration), hasAudio="1", audioSources="1", audioChannels="2", audioRate=str(RATE))
        ET.SubElement(beep, "media-rep", kind="original-media", src=(media_dir / f"beep_{i + 1:04d}.wav").resolve().as_uri())
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Auto Censor")
    project = ET.SubElement(event, "project", name=f"{source.stem} — censored")
    sequence = ET.SubElement(project, "sequence", format="r1", duration=rational_time(duration),
                             tcStart="0s", tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(sequence, "spine")
    original = ET.SubElement(spine, "asset-clip", ref="r2", name=source.name, offset="0s",
                            start=rational_time(info.timecode), duration=rational_time(duration), srcEnable="video")
    ET.SubElement(original, "asset-clip", ref="r3", name="Censored original audio", lane="-1",
                  offset=rational_time(info.timecode), start="0s", duration=rational_time(duration), audioRole="dialogue")
    lane_ends: list[int] = []
    for i, item in enumerate(ranges):
        lane = next((j for j, end in enumerate(lane_ends) if end <= samples(item.start)), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(0)
        lane_ends[lane] = samples(item.start) + samples(cue_duration)
        ET.SubElement(original, "asset-clip", ref=f"r{i + 4}", name=f"BEEP {i + 1:03d}", lane=str(-2 - lane),
                      offset=rational_time(info.timecode + Fraction(samples(item.start), RATE)),
                      start="0s", duration=rational_time(cue_duration), audioRole="effects")
    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def export_fcpxml(source: Path, sound: Path, output: Path, info: MediaInfo,
                  ranges: list[CensorRange], mode: str, duck_db: float, work: Path) -> None:
    media_dir = output.with_name(output.stem + "_media")
    if media_dir.exists() or output.exists():
        raise CensorError(f"FCPXML or media folder already exists: {output}, {media_dir}")
    tree = build_xml(source, info, media_dir, ranges, sound_duration(sound))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fcpxml-", dir=output.parent) as folder:
        staged = Path(folder) / "media"
        staged.mkdir()
        render_bed(source, staged / "original_censored.wav", info, ranges, mode, duck_db, work)
        for i, item in enumerate(ranges):
            render_beep(sound, staged / f"beep_{i + 1:04d}.wav")
        # Reserve the destination; an existing directory is never replaced.
        media_dir.mkdir()
        try:
            for path in staged.iterdir():
                path.rename(media_dir / path.name)
            with new_output(output) as xml_path:
                with xml_path.open("wb") as handle:
                    handle.write(b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE fcpxml>\n')
                    tree.write(handle, encoding="utf-8", xml_declaration=False)
        except BaseException:
            shutil.rmtree(media_dir)
            raise
