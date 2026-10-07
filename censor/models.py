from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class WordTimestamp:
    word: str
    start: float
    end: float
    profane: bool = False


@dataclass(frozen=True, order=True)
class CensorRange:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    video_index: int
    audio_index: int  # absolute ffprobe stream index
    audio_count: int
    width: int
    height: int
    fps: Fraction
    start: float = 0.0  # first video PTS, distinct from editorial timecode
    timecode: Fraction = Fraction(0)
    color_space: str | None = None
