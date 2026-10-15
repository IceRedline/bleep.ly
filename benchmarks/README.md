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

On an Apple Silicon Mac with macOS 15 or newer, **double-click
[`Run Speed Test.command`](../Run%20Speed%20Test.command)** in the repository folder
or an extracted source ZIP. The 14 MiB reference FLAC is included, so there is no
separate audio file to find or copy. If macOS asks how to open a `.command` file,
choose Terminal; a downloaded script may require approval in Privacy & Security.

The launcher installs missing Command Line Tools, Homebrew, Python 3.11 and
FFmpeg 8, prepares an isolated benchmark environment, builds WhisperKit, downloads
the pinned model weights, and runs all 12 measurements. macOS and the official
Homebrew installer may ask for installation approval or an administrator password;
the launcher does not bypass those prompts. Keep the Terminal window open until
it finishes. Downloads can require several GB and are excluded from timing.

The script prevents idle system sleep while measuring and opens a new folder
under **Desktop → bleeply Speed Test** when finished. Send **`report.json` and
`report.md`** from that folder. `status.txt` distinguishes success, incomplete
runs and setup failures; `setup.log` is local troubleshooting output and may
contain local paths. Raw worker logs and transcripts stay in the ignored cache.
No recordings or results are uploaded. Another launch reuses installed tools and
models and creates a new report folder. Concurrent launchers are rejected.

If only the `.command` file is copied to another Mac, it automatically obtains
the repository from GitHub into `~/Library/Caches/bleeply-speedtest/source`.
That mode requires the launcher and fixture changes to have been published on
`main`. An extracted source ZIP is self-contained apart from dependency/model
downloads. Git checkouts record their revision; source ZIPs record an executable
source fingerprint with null Git fields instead of claiming a nonexistent commit.

Close heavy applications, turn Low Power Mode off and keep the machine's power
and cooling conditions consistent. The committed M3 Pro result used battery
power. Do not run benchmark processes in parallel.

### Terminal / advanced usage

From the repository folder, the same automated workflow is:

```sh
bash "Run Speed Test.command"
```

`--prepare-only` installs and verifies prerequisites without measuring;
`--output "/path/to/new report folder"` overrides the Desktop destination. An
existing report directory is never overwritten. If installation is interrupted,
finish any system installer and launch the script again.

For an already configured development machine:

```sh
make speedtest-setup
make speedtest
```

Setup uses `.cache/speedtest/venv`, leaving the development environment alone. It
selects the release's SHA-256-pinned **macOS 15 MLX wheels**, including on newer
Macs where pip would otherwise choose a different binary. Reports record wheel
tags as well as version numbers; compare matching binaries across machines.

The default audio is `benchmarks/fixtures/turbo-en.flac`. Each invocation of
`make speedtest` creates a new `.cache/speedtest/run-*` folder. There is one initial
run plus three measured runs per pipeline, a 15 s idle gap and a one-hour limit
per run. The launcher uses the same settings. On an M1 CPU the complete test may
take a while.

```sh
make speedtest SPEEDTEST_ARGS="--repeats 3 --timeout 3600 --cooldown 15"
```

To contribute a result, copy only `report.json` and `report.md` into
`benchmarks/results/<chip>-<memory>-<date>.*`, then update the table here and in the
main README. Failed, timed out, empty or cached runs cannot produce a successful
median. A failed pipeline is recorded and the others still run; the command
returns nonzero. A setup failure produces a status/log, not a fabricated timing.

## Reference audio

The reference is the complete author-hosted Odysee version of
[Cinemassacre's Silver Surfer / AVGN Episode 27](https://cinemassacre.com/silver-surfer-nes-angry-video-game-nerd-avgn-episode-27/).
It contains explicit language. The YouTube version differs in length.
[The manifest](turbo-en.json) pins the source video SHA-256, the included FLAC
SHA-256, decoded 16 kHz mono signed-16-bit PCM hash, sample count and model revisions.

The immutable [reference FLAC](fixtures/turbo-en.flac) is deliberately tracked in
Git; other recordings, model weights and generated media remain excluded. The
recording belongs to Cinemassacre; see [fixture provenance](fixtures/README.md).
Timed runs decode audio only. The script validates decoded PCM before any model
runs, so equivalent FLAC metadata / encoder changes do not alter the test input.

To reproduce the extraction from the exact original recording without replacing
the committed reference:

```sh
make speedtest-audio VIDEO="/path/to/silver-surfer-official.mp4" AUDIO=".cache/speedtest/recreated.flac"
```

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
