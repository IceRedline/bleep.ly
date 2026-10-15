# Turbo speed test across Macs

One full English **audio** reference, Whisper Large v3 Turbo, three application
pipelines. Run `make speedtest` on each Mac and contribute the generated report.
M1 and M3 results must be measured on those machines; they cannot be inferred
from M3 Pro timings.

| Mac | Memory | CPU: faster-whisper int8 | GPU: MLX float16 | CPU + Neural Engine: WhisperKit |
| --- | ---: | ---: | ---: | ---: |
| M1 Air | 8 GiB | Not measured | Not measured | Not measured |
| M3 | — | Not measured | Not measured | Not measured |
| M3 Pro | 36 GiB | 170.37 s | 41.49 s | 51.24 s |

M3 Pro measurement: 12 CPU / 18 GPU cores, macOS 26.6.2 (25G83), battery
power, Low Power Mode off. [Readable report](results/m3-pro-36gb-2026-10-15.md) ·
[Full measurements and provenance](results/m3-pro-36gb-2026-10-15.json).

Cells report median wall time in seconds for **three fresh worker processes**
after one initial run per pipeline. Every run processes the complete 628.471 s
recording. Smaller is faster. The initial run, all individual measurements,
software versions, model fingerprints and hardware details are retained in JSON.

## Run on another Mac

Prerequisites: Apple Silicon, macOS 15+, Python 3.11, FFmpeg / FFprobe, Xcode
Command Line Tools and Git. Use a local terminal with Metal / Core ML access.
Connect power, turn Low Power Mode off, close heavy applications and keep the
machine's cooling conditions consistent. Do not run benchmark processes in parallel.

```sh
# Install pinned inference dependencies, build the helper, download models once.
# This is deliberately separate from the measured, offline run.
make speedtest-setup

# Copy the reference FLAC from the first Mac, then use its local path.
make speedtest AUDIO="/path/to/turbo-en.flac"
```

Setup uses a dedicated `.cache/speedtest/venv`, leaving the development environment
alone. It selects the release's SHA-256-pinned **macOS 15 MLX wheels**, including
on newer Macs where pip would otherwise choose a different binary. Reports record
wheel tags as well as version numbers; compare matching binaries across machines.

With the default location `.cache/speedtest/turbo-en.flac`, just run
`make speedtest`. Each invocation creates a new `.cache/speedtest/run-*` folder;
it never resumes or overwrites an old measurement. The default is one initial
run plus three measured runs for each pipeline, a 15 s idle gap and a one-hour
limit per run. On an M1 CPU the complete test may take a while.

```sh
make speedtest SPEEDTEST_ARGS="--repeats 3 --timeout 3600 --cooldown 15"
```

The final folder contains `report.json` and `report.md`. Copy **only those two**
files into `benchmarks/results/<chip>-<memory>-<date>.*` when contributing results,
and update the table above. Reports contain no transcript, user name, host name,
serial number or local source path. Raw worker requests, transcripts, errors and
recognition history stay in the ignored local output directory. Failed, timed
out, empty or cached runs cannot produce a successful median. A failed pipeline
is recorded and the other pipelines still run; the command returns nonzero.

## Reference audio

The reference is the complete author-hosted Odysee version of
[Cinemassacre's Silver Surfer / AVGN Episode 27](https://cinemassacre.com/silver-surfer-nes-angry-video-game-nerd-avgn-episode-27/).
It contains explicit language. The YouTube version differs in length.
[The manifest](turbo-en.json) pins the source video SHA-256 and the decoded
16 kHz mono signed-16-bit PCM hash, sample count and model revisions.

If you have the exact original recording, generate the small lossless audio once:

```sh
make speedtest-audio VIDEO="/path/to/silver-surfer-official.mp4"
```

This extracts the full first audio stream without cuts or normalization into a
roughly 14 MiB FLAC. There is no video decoding in timed runs. The script checks
the decoded PCM hash before running any model, so FLAC metadata / encoder version
changes do not invalidate identical sound. Copy this FLAC to other Macs. Media
and model weights are **not stored in Git**; the author retains the recording's
rights. There is no automatic redistribution or download of the recording.

## What the numbers mean

This measures the application's real Python `censor.desktop` analysis path:
process startup, audio preparation, model loading, recognition with word
timestamps, classification and local result/history writing. It excludes UI,
preview rendering, export, dependency setup and model downloads. Transcript
caches are bypassed; inference is offline. Models are pinned and their files are
hashed before measurement. The `make speedtest-setup` step installs fixed core
inference versions; the report records their actual versions for comparison.

- **CPU:** CTranslate2 / faster-whisper, int8, beam 5, Silero VAD, CPU threads
  left at the application's library default (4 for the pinned version).
- **GPU:** MLX Whisper, float16, greedy decoding, the same Silero VAD.
- **CPU + Neural Engine:** WhisperKit 1.1.0 / Core ML, CPU-only mel processing,
  CPU + Neural Engine encoder and decoder, SDK VAD and incremental audio.
  GPU is excluded by this benchmark policy. Core ML can still use CPU for
  individual operations; this is not proof of exclusive ANE execution. Normal
  app requests retain SDK defaults, which allow GPU for mel processing.

These are different runtimes and precisions for the same Turbo model family,
not an isolated CPU-versus-GPU hardware experiment. Compare the **same column**
across Macs, with the same fixture, revisions, software versions and settings.
This is a speed test, not an accuracy benchmark. RTF is elapsed / audio duration;
for example 0.1 means ten times faster than real time.

## First-run WhisperKit preparation

`native_metrics.load_seconds` separates Core ML model prewarming / loading from
`inference_seconds`. Downloads occur in `prepare`, outside both values.
The first observed run is reported separately, never included in the median.
It is **not a guaranteed cold run**: macOS may already have a specialized model
cache, and we do not delete system caches to manufacture a cold condition.

WhisperKit explains that device-independent models are specialized on first
load and cached by Core ML. Its sequential prewarm reduces peak compilation
memory, which matters on an 8 GiB M1, but adds a load/unload/load cycle.
See the [SDK's prewarm documentation](https://github.com/argmaxinc/argmax-oss-swift/blob/v1.1.0/Sources/WhisperKit/Core/Configurations.swift).
An 11-minute first setup is possible, but that duration alone does not establish
that everything is healthy. Separate download time, first `load_seconds`, and
repeated `load_seconds` before diagnosing it. Repeated multi-minute loading
warrants investigation of cache reuse, memory pressure and model installation.

For context, a January 2025 [upstream user report](https://github.com/argmaxinc/argmax-oss-swift/issues/268)
describes nearly ten minutes to first-load the 632 MB Turbo variant on an M1 Pro.
That is an anecdote from a different model variant / SDK setup, not a timing
guarantee for this application or evidence that every long load is healthy.
