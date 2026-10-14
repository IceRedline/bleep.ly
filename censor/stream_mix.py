"""Bounded-memory export mixing; never run a full-length branch per cue."""
import subprocess
import tempfile
from contextlib import contextmanager, suppress

import numpy as np

from .audio import FADE, RATE, bed_filter, beep_filter, samples
from .ffmpeg import input_args, run, sound_duration
from .utils import CensorError

BLOCK = RATE  # One second of stereo float PCM, independent of recording length.


@contextmanager
def cue_samples(cue, work):
    if cue is None:
        yield None
        return
    raw = work / "cue.f32"
    # The reference graph applies these edge fades to the prepared cue as well.
    run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(cue),
         "-map", "0:a:0", "-af", beep_filter(sound_duration(cue)),
         "-ar", str(RATE), "-ac", "2", "-f", "f32le", str(raw)])
    if not raw.stat().st_size or raw.stat().st_size % 8:
        raise CensorError("Censor sound contains no complete stereo samples.")
    # Even a long custom cue stays on disk rather than being loaded into RAM.
    data = np.memmap(raw, dtype="<f4", mode="r").reshape(-1, 2)
    try:
        yield data
    finally:
        data._mmap.close()


class BlockMixer:
    def __init__(self, ranges, cue):
        self.ranges = sorted(ranges)
        self.cue = cue
        self.cue_duration = len(cue) / RATE if cue is not None else 0
        self.next_range = 0
        self.active = []

    def mix(self, data, start):
        lo, hi = start / RATE, (start + len(data)) / RATE
        self.active = [r for r in self.active
                       if max(r.end + FADE, r.start + self.cue_duration) > lo]
        while self.next_range < len(self.ranges):
            item = self.ranges[self.next_range]
            if item.start - FADE >= hi:
                break
            self.active.append(item)
            self.next_range += 1
        if not self.active:
            return data
        t = np.arange(start, start + len(data), dtype=np.float64) / RATE
        amount = np.zeros(len(data), dtype=np.float64)
        for item in self.active:
            if item.end + FADE > lo:
                # Match FFmpeg's sample envelope, including overlapping fades.
                amount += np.clip(np.minimum((t - (item.start - FADE)) / FADE,
                                             ((item.end + FADE) - t) / FADE), 0, 1)
        # Keep double precision through the limiter, like aeval/amix in the
        # reference graph. Rounding to float here can change limiter release.
        mixed = data * (1 - np.minimum(1, amount))[:, None]
        if self.cue is not None:
            for item in self.active:
                onset = samples(item.start)
                first, last = max(start, onset), min(start + len(data), onset + len(self.cue))
                if first < last:
                    mixed[first - start:last - start] += self.cue[first - onset:last - onset]
        return mixed


@contextmanager
def worker(command, **pipes):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stderr=errors, **pipes)
        try:
            yield process
            for stream in (process.stdin, process.stdout):
                if stream:
                    with suppress(BrokenPipeError):
                        stream.close()
            code = process.wait()
            if code:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 5000))
                raise CensorError(f"Audio processing failed:\n{errors.read().decode(errors='replace')}")
        except BaseException as exc:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if isinstance(exc, BrokenPipeError) and process.stdin is not None:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 5000))
                raise CensorError(f"Audio encoder failed:\n{errors.read().decode(errors='replace')}") from exc
            raise
        finally:
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed:
                    with suppress(BrokenPipeError):
                        stream.close()


def render_track(source, output, info, ranges, cue, progress=None, *, floating=False):
    """Decode once, apply only active envelopes/cues, and encode through a pipe."""
    decoder = ["ffmpeg", "-v", "error", "-nostdin", *input_args(source, info),
               "-map", f"0:{info.audio_index}", "-af", bed_filter(info, [], "mute", -30),
               "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]
    encoder = ["ffmpeg", "-v", "error", "-nostdin", "-n",
               "-f", "f64le", "-ar", str(RATE), "-ac", "2", "-i", "pipe:0",
               *input_args(source, info), "-map", "0:a:0", "-map_metadata", "1",
               *(["-af", "alimiter=limit=0.98:level=0:latency=1"] if cue is not None and ranges else []),
               "-c:a", "pcm_f32le" if floating else "pcm_s24le", "-rf64", "auto", str(output)]
    mixer = BlockMixer(ranges, cue)
    frames = samples(info.duration)
    with worker(encoder, stdin=subprocess.PIPE) as sink:
        with worker(decoder, stdout=subprocess.PIPE) as source_process:
            for start in range(0, frames, BLOCK):
                count = min(BLOCK, frames - start)
                raw = source_process.stdout.read(count * 8)
                if len(raw) != count * 8:
                    raise CensorError("Incomplete source audio while exporting.")
                data = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
                sink.stdin.write(mixer.mix(data, start).astype("<f8", copy=False).tobytes())
                if progress:
                    progress((start + count) / RATE)
