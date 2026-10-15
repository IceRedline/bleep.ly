<p align="center"><img src="icon.PNG" alt="bleeply icon" width="128"></p>

# bleeply

Find and censor profanity in video and audio on your Mac. Use a beep, silence or
your own sound, review detected words on a timeline, and export the result.
Russian is supported, with experimental English support. Speech recognition and
processing run locally; your recordings stay on your Mac.

[Privacy Policy](docs/privacy-policy.md) · [Support](docs/support.md) · [Open Source Licenses](docs/third-party.md)

**Contents:** [Download](#download-for-macos) · [Setup](#setup) · [App workflow](#app-workflow) · [Recognition](#recognition) · [Turbo benchmark](#turbo-benchmark) · [Exports](#exports) · [Architecture](#architecture) · [CLI](#cli) · [Checks](#checks) · [Limitations](#limitations)

## Download for macOS

**Requires an Apple Silicon Mac running macOS 15.0 or later.**

1. [Download bleeply 0.1.9](https://github.com/IceRedline/bleeply/releases/download/v0.1.9/bleeply-0.1.9-arm64.dmg).
2. Open the DMG and drag **bleeply** to **Applications**.
3. Open **bleeply** from Applications and choose a video or audio file.
4. If prompted, allow the selected speech model to download. Once it is downloaded, recognition works offline.

The app is signed with Developer ID and notarized by Apple. Python, FFmpeg and
the recognition engines are included. Model downloads can be several GB;
Settings shows an estimate for the selected model. Recordings are processed on
your Mac. An Intel installer is not available.

[Release notes and checksums](https://github.com/IceRedline/bleeply/releases/tag/v0.1.9)
· [macOS user guide](macOS/README.md)

### Updating an existing installation

If bleeply is already installed, close it before replacing it in Applications.
Settings, downloaded models and the last saved review are retained.

When updating from a version with the former app name, launch the new app once
to migrate its data to `~/Library/Application Support/bleeply/`. After confirming
your saved work is available, remove the old application from Applications.
Keep its Application Support data until migration has succeeded.

The setup below is for building from source. See the
[release build instructions](scripts/release/README.md) for packaging and signing.

## Setup

The Swift app targets macOS 14+. Building the included WhisperKit helper requires
Swift 5.10 or later. Install Xcode with its Swift toolchain, Python 3.11, and
FFmpeg 8. GPU backends require Apple Silicon and may impose a higher macOS minimum
through their Python packages; the release's macOS 15 compatibility is checked
separately with pinned dependencies.

```sh
git clone https://github.com/IceRedline/bleeply.git
cd bleeply
brew install ffmpeg@8 python@3.11
brew link --force ffmpeg@8
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/build-macos.sh --open
```

The build command opens `build/bleeply.app`; you can also open it from Finder later. This is a local development build with an ad-hoc signature: the repository, Python environment, FFmpeg, and model files remain external dependencies. If the repository moves, rebuild or update its location in Settings (`⌘,`).

For Whisper recognition on Apple GPU, also install:

```sh
.venv/bin/pip install -r requirements-mlx.txt
```

Opening a file with a missing model asks **Download model?**. Choose **OK** to allow missing-model downloads and continue automatically, or **No** to cancel without downloading. The choice is remembered and can be changed with **Allow first-time model download** in Settings. Cached models work offline without a prompt. Models use the repository's `.cache/huggingface` (or an inherited `HF_HOME`).

## App workflow

Choose **Video language → Русский / English** on the home screen before opening media.
The saved choice controls recognition and the profanity dictionary. Changing to Russian
selects GigaAM v3; changing to English selects Whisper Large v3 Turbo. Both keep
CPU if already selected, otherwise use Apple GPU. Intel Macs use Whisper on CPU.
The subtitle shows the selected model and language. You can override it in Settings until the next language
change; relaunching or selecting the same language keeps your manual choice. GigaAM
is the Russian preset selected on a language change, based on the local trial,
not a proven accuracy winner. With no saved preferences, the app starts in
Russian with CPU / Whisper Large v3.
Settings hides GigaAM for English. Downloads still
require **Allow first-time model download**. English detection uses an experimental
word list (`profanity.en.txt`); review contextual false positives and missed words.
There is no automatic language detection or mixed-language censorship mode. Parakeet
itself auto-detects speech language; the selected language controls its profanity list.
Language is recorded in reviews and recognition history, and English/Russian runs use
separate caches. Changing language applies to the next file.

The app reuses recognition results across normal relaunches of the same installed
build. Updating, rebuilding, or reinstalling the app (even the same version)
starts a new recognition cache, so old transcripts cannot hide fixes in the new
app. Previously downloaded models remain available. **Resume Last Review** and
explicit transcript imports preserve saved manual edits; open the source media
again to obtain a fresh transcript after an update.

- **Fast Mode:** select Beep, Silence, or custom audio, then drop a file. After recognition, choose **Save as Video** (primary) or **Save as Audio** (secondary). Audio-only sources show only **Save as Audio**. Each action opens a save dialog so you choose the destination; nothing is exported before you confirm. You can save both formats from the same analysis. Existing files are never overwritten.
- **Advanced:** review detections on the timeline, uncheck false positives, flag other transcript words, add missing intervals, and adjust mute boundaries. Unchecked words stay in **Flagged** without a checkmark so they can be enabled again, including after reopening the saved review. `⌘Z` undoes review edits. **Listen in Context** plays the word with **0.2 seconds before and 0.2 seconds after**, clipped at the file boundaries. **Choose Beep, Silence, or Custom before dropping media.** Preview with censorship is enabled by default and prepares automatically after analysis. The original stays playable during preparation; the player switches to censored audio at the current position when ready. Both Play and Listen in Context use it; turn the checkbox off to hear the original. During playback, Review Words highlights and scrolls to each censored word on the selected track, keeping the last heard word highlighted between intervals.
- **Multiple audio tracks:** both modes analyze each track independently. Advanced shows separate timeline rows and a track selector for listening and editing. Video export preserves separate processed audio tracks.
- **Home:** click the logo, the Home button, or press `⌘⇧H`. During processing this cancels the worker and returns to file selection. **Resume Last Review** restores the latest autosaved review.

Downloads show received bytes and the total size when available. Media checks
and model preparation show an activity indicator with a description of the current
step. Recognition and export show progress, elapsed time and an estimated time
remaining. Approximate values are marked with ≈; an estimate appears only once
there is enough progress to calculate it.

**Settings → Censoring → Edit word lists…** edits the full censor list and a
**Never censor** list separately for Russian and English. Lists accept one word per
line, optional trailing `*` for prefix matching, and `#` comments. Known Russian
censor stems retain their morphological families; exceptions match exact words or
explicit prefixes and take priority. Empty censor lists disable automatic flags.
Save validates both language drafts before persisting; Cancel discards edits, and
Reset restores the selected language's defaults in the draft until Save. Changes
apply when opening a file again, including cached recognition. Imported/saved
reviews keep their manual flags. Recognition history records the effective rules
and their hash, so comparisons made with different lists remain distinguishable.

In Settings, choose **Word middle** (default) or **Whole word**. The choice applies to newly analyzed/imported media. Existing reviews and manual edits keep their timing. The selected sound mode is remembered across launches. Custom audio is copied into the app’s support folder, so moving or deleting the original cue does not lose it. A custom sound plays **once, in full, at its original speed**; speech resumes at the approved mute endpoint underneath any remaining sound tail. The cue never extends the mute interval. The end of the media still limits the output.

See the [macOS guide](macOS/README.md) for shortcuts, drafts, and development details.

## Recognition

One **Engine** picker selects the backend for the next file:

| Engine | Processing | Availability in the DMG |
| --- | --- | --- |
| CPU · Classic processing | Whisper through faster-whisper (int8); Parakeet, Qwen3-ASR and GigaAM on CPU (float32) | Included; non-Whisper models require Apple Silicon |
| Apple GPU · MLX / MPS | Whisper, Parakeet and Qwen3-ASR through MLX; GigaAM through PyTorch MPS | Included; Apple Silicon |
| WhisperKit · Experimental | Native Swift helper running converted Whisper weights through Core ML | Included; experimental |

All engines still require a separate model download. For source builds, install
the additional recognition dependencies described below.

In **Settings → Recognition**, the **Model · testing** picker offers Whisper
Large v3 (the default) and Large v3 Turbo for CPU and Apple GPU. WhisperKit uses
Large v3 Turbo through Core ML. Engine and model changes apply to the next file;
each configuration has its own recognition cache.

On Apple Silicon, both **CPU** and **Apple GPU · MLX / MPS** also offer experimental **Parakeet v3**,
**Parakeet Ultra**, **Qwen3-ASR 1.7B**, and **GigaAM v3 RNNT**. Their runtime is
already included in the DMG. For a source build, install it with
`bash scripts/setup-experimental-gpu.sh`. The development app selects
`.runtime/asr-env/bin/python` automatically for these models unless a custom Python
executable is configured. The standard development runtime remains in `.venv`;
the release selects its bundled runtimes automatically.
Model weights download on first use only when downloads are enabled. These
models run on the selected device, including their word alignment. CPU runs use
float32 and disable MLX JIT compilation, so they do not require a compiler or
loading generated libraries. They can be slower and use more memory than GPU
runs, especially Qwen3-ASR on an 8 GB Mac. CPU and GPU recognition caches are
separate; downloaded weights are shared. GPU selection still reports unavailable
GPU support without silently falling back. See [GPU comparison](experiments/gpu-models.md) for pinned weights,
timestamps, and the full-file benchmark command.

GigaAM uses overlapping speech windows to retain words at chunk boundaries, then
Qwen3-ForcedAligner refines their timing against the audio. GigaAM therefore also
downloads the pinned aligner weights (about 1.84 GB), through the same first-use
download permission. Ambiguous alignments are retried with local context; words
that still cannot be located reliably keep their original timing for review.
Alignment retry/fallback counts are recorded in recognition history. This does
not change existing reviews, manual mute intervals, or custom-cue playback.

WhisperKit remains experimental. See the [WhisperKit guide](experiments/README.md) for setup and the results of a small local comparison; those results are not a general accuracy ranking.

For development, `requirements.txt` already includes the Python dependencies for
WhisperKit model downloads; `scripts/build-macos.sh` builds its Swift helper.

The build includes the native WhisperKit helper. Model weights download on first use with permission, or can be prepared with `scripts/prepare-whisperkit.py`. Initial Core ML preparation can take several minutes.

## Turbo benchmark

Whisper Large v3 Turbo on the same **628.47-second English audio recording**.
Times are the **median of three repeated runs**, after one separate initial run
per pipeline. Smaller is faster; transcript caches are bypassed.

| Mac | Memory | CPU: faster-whisper int8 | GPU: MLX float16 | CPU + Neural Engine: WhisperKit |
| --- | ---: | ---: | ---: | ---: |
| M1 Air | 8 GiB | Not measured | Not measured | Not measured |
| M3 | — | Not measured | Not measured | Not measured |
| M3 Pro | 36 GiB | 170.37 s | 41.49 s | 51.24 s |

Measured on an M3 Pro with 12 CPU / 18 GPU cores, macOS 26.6.2, battery power,
and Low Power Mode off. These are application pipelines with different runtimes,
precisions and decoding settings; compare the same column across Macs. Core ML
may use CPU for some operations in the Neural Engine column.

[Full results and setup instructions](benchmarks/README.md) ·
[Individual measurements](benchmarks/results/m3-pro-36gb-2026-10-15.json)

To measure another Mac, prepare the benchmark environment with
`make speedtest-setup`, then run `make speedtest` with the reference audio.
Audio, models and detailed logs stay outside Git.

## Exports

| App format | Result |
| --- | --- |
| **Audio Only** | 48 kHz, 24-bit stereo WAV; multiple processed tracks are mixed into one stereo track |
| **Video** | Original video stream copied without re-encoding; each processed audio track retained separately as AAC |

MOV, MP4, and MKV are supported output containers. A codec/container mismatch produces an error; there is no silent video re-encoding fallback. Subtitles, alternate video angles, and additional data streams are not preserved. Original recordings and existing outputs remain intact.

FCPXML and JSON export are available through the CLI; they are not app export options in this version.

## Architecture

The shipped app uses **SwiftUI and AVKit for the interface and playback**, plus
**Python for recognition orchestration, profanity matching, mute intervals,
caching, and export orchestration**. The Swift app exchanges JSON messages with
Python worker processes. FFmpeg handles media extraction, audio mixing and export.
WhisperKit inference runs in a native Swift/Core ML helper launched by the Python
worker; choosing WhisperKit does not currently remove the Python dependency.

The release embeds two Python environments to preserve the tested dependency
versions for its recognition backends. Model weights are downloaded separately
and run locally.

## CLI

```sh
export HF_HOME="$PWD/.cache/huggingface"
.venv/bin/python bleep.py input.mov --sound beep.wav --backend faster-whisper
.venv/bin/python bleep.py input.mov --sound beep.wav --backend mlx --offline
.venv/bin/python bleep.py input.mov --transcribe-only
.venv/bin/python bleep.py input.mov --from-transcript input.transcript.json \
  --sound beep.wav --output reviewed.mov
.venv/bin/python bleep.py --help
```

The CLI keeps its explicit single-audio-track workflow (`--audio-stream 0` for a file with multiple streams). Unlike the app, it does not automatically process all tracks. `censor.py` remains a compatible entry point.

The [CLI guide](docs/cli.md) covers reviewed JSON, word matching, mute/duck timing, speaker-specific sounds, FCPXML, cache behavior, and limitations.

## Checks

GitHub Actions runs the complete Python suite on Ubuntu and the complete Swift
app suite on macOS for every pull request and push to `main`. The **Tests**
workflow can also be started manually. Both jobs install Python 3.11, the engine
dependencies in `.venv`, and FFmpeg so media and Swift → Python integration tests
run on a fresh checkout. macOS uses FFmpeg 8 because the engine's
`filter_complex_script` option was removed in FFmpeg 9.
Model downloads are disabled; inference is mocked.
The one Python check against `input.reviewed.transcript.json` is skipped in CI
because the approved personal recording and transcript are local, ignored files.

Two additional jobs install the complete core and GPU release dependencies on
macOS 15. They check dependency consistency, native library deployment targets,
backend imports and MLX CPU execution. Hosted runners lack Metal GPU access;
GPU execution and real model inference are checked separately during local
release smoke tests. See [release checks](scripts/release/README.md).

Each successful app recognition records one history row per audio track in
`recognition-history/runs.csv`. In a release build this lives under
`~/Library/Application Support/bleeply/`; in a development build, under
`тесты bleeply/` inside the selected project folder. It includes the exact model,
engine/device, total and flagged word counts, source hash, track index, elapsed
analysis/inference time, and cache-hit status. A cache
hit has no inference time. WhisperKit uses automatic Core ML device selection;
it is not labelled as a GPU-only run. Counts measure flagged ASR tokens, not
verified profanity recall. JSON snapshots preserve all words and cache metadata;
each snapshot also has a word-level CSV. Repeated runs remain separate even if
they replace the same recognition cache. The matcher hash identifies which
dictionary/code produced the count. History is local and excluded from Git.

Import existing caches (safe to repeat; changed cache contents create another record):

```sh
.venv/bin/python scripts/import-recognition-history.py \
  --output 'тесты bleeply/recognition-history' \
  "$HOME/Library/Application Support/bleeply/cache"
```

Additional cache folders can be passed as positional arguments.
Optional `--source /path/to/video` attaches the filename and duration only to
caches with the same SHA-256. Imported records are labelled `cache_import` and
reclassified with the current matcher. Old run time, cache-hit status, and
inference duration are unknown and left blank; cache modification time is a
separate column. This cannot recover runs already overwritten before logging
was enabled. Logging failures go to the worker log without discarding results.

```sh
.venv/bin/python -m unittest discover -s tests -q
CLANG_MODULE_CACHE_PATH="$PWD/.cache/clang" \
SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.cache/clang" \
swift test --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
```

Python integration tests generate short media with FFmpeg and check actual audio, independent track censorship, complete cue tails, video stream identity, cache behavior, and no-clobber exports. Swift tests cover the real Python bridge, native playback, explicit video/audio saving, cancellation/Home, progress, context duration, and stable window layout. Native tests need a local macOS session with media services. Inference is mocked in regression tests; actual engine comparison is a separate offline benchmark.

For repeatable Turbo CPU / MLX GPU / Core ML measurements across Macs, use
[`make speedtest`](benchmarks/README.md). It checks one fixed English audio fixture,
reports first-run preparation separately, and records three repeated runs per pipeline.

Code lives in `censor/`, the SwiftUI app in `macOS/`, the experimental native helper in `experiments/WhisperKitRunner/`, and build tools in `scripts/`. Source media, transcripts, generated exports, weights, virtual environments, and caches are excluded from Git.

## Limitations

Recognition can miss words or place approximate boundaries, especially with music,
overlapping voices, shouting or fast speech. Review important material in Advanced
and listen to the export. English detection is experimental. Muting affects the
entire selected audio track, including music; it does not separate voices from a
mixed recording.

Censored previews use temporary decoded audio and need free disk space. The preview
cache has a 7 GiB session budget and requires at least 1 GiB of free disk space.
If a preview cannot fit, original playback and export remain available. Recognition
cache and history share a 256 MiB budget and a 30-day retention period. Cleanup
preserves models, original recordings, exports, custom sounds and the saved review.
See the [macOS guide](macOS/README.md#workflow) for preview and storage details.

Video export keeps the original video stream and processed audio tracks. Subtitles,
alternate video angles and additional data streams are not preserved. Waveform zoom
is not available. FCPXML and JSON export are available through the CLI only.
