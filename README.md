<p align="center"><img src="icon.PNG" alt="bleep.ly icon" width="128"></p>

# bleep.ly

Local speech recognition and profanity censoring for Russian video and audio, with experimental English support in the desktop app. A native **macOS app** wraps the Python engine with drag and drop, a review timeline, and clean audio/video export. Your recordings stay on your Mac.

**Contents:** [Setup](#setup) · [App workflow](#app-workflow) · [Recognition](#recognition) · [Exports](#exports) · [CLI](#cli) · [Checks](#checks) · [Limitations](#limitations)

## Setup

Requires macOS 14+, Swift 5.9+, Python 3.11+, and FFmpeg. MLX requires Apple Silicon.

```sh
git clone https://github.com/IceRedline/bleep.ly.git
cd bleep.ly
brew install ffmpeg python@3.11
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/build-macos.sh --open
```

Open `build/bleep.ly.app` from Finder afterwards. This is a local development build with an ad-hoc signature: the repository, Python environment, FFmpeg, and model files remain external dependencies. If the repository moves, rebuild or update its location in Settings (`⌘,`).

Optional Apple GPU recognition:

```sh
.venv/bin/pip install -r requirements-mlx.txt
```

Enable **Allow first-time model download** in Settings if the selected model is not installed. Downloads are disabled by default. Once installed, recognition works offline. Models use the repository's `.cache/huggingface` (or an inherited `HF_HOME`).

## App workflow

Choose **Video language → Русский / English** on the home screen before opening media.
The saved choice controls recognition and the profanity dictionary. Changing to Russian
selects GigaAM v3 on Apple GPU; changing to English selects Whisper Large v3 (keeping
CPU if already selected, otherwise using Apple GPU). Intel Macs use Whisper on CPU.
A notice explains the choice. You can override it in Settings until the next language
change; relaunching or selecting the same language keeps your manual choice. GigaAM
is our current Russian default based on the local trial, not a proven accuracy winner.
Settings hides GigaAM for English. Downloads still
require **Allow first-time model download**. English detection uses an experimental
word list (`profanity.en.txt`); review contextual false positives and missed words.
There is no automatic language detection or mixed-language censorship mode. Parakeet
itself auto-detects speech language; the selected language controls its profanity list.
Language is recorded in reviews and recognition history, and English/Russian runs use
separate caches. Existing Russian benchmark caches remain reusable (WhisperKit helper
changes still invalidate its cache). Changing language applies to the next file.

- **Fast Mode:** select Beep, Silence, or custom audio, then drop a file. Recognition and export run automatically. The result is saved beside the source as `NAME_censored.ext`; existing files receive a numbered alternative and are never overwritten.
- **Advanced:** review detections on the timeline, uncheck false positives, flag other transcript words, add missing intervals, and adjust mute boundaries. `⌘Z` undoes review edits. **Listen in Context** plays the word with **0.2 seconds before and 0.2 seconds after**, clipped at the file boundaries. **Choose Beep, Silence, or Custom before dropping media.** Preview with censorship is enabled by default and prepares automatically after analysis. The original stays playable during preparation; the player switches to censored audio at the current position when ready. Both Play and Listen in Context use it; turn the checkbox off to hear the original. During playback, Review Words highlights and scrolls to each censored word on the selected track, keeping the last heard word highlighted between intervals.
- **Multiple audio tracks:** both modes analyze each track independently. Advanced shows separate timeline rows and a track selector for listening and editing. Video export preserves separate processed audio tracks.
- **Home:** click the logo, the Home button, or press `⌘⇧H`. During processing this cancels the worker and returns to file selection. **Resume Last Review** restores the latest autosaved review.

The drop target stays in place when switching modes; controls below it fade. The window background extends behind the native traffic lights and changes color with the processing stage.

Reading media uses a simple activity indicator without percentages. Other stage progress uses worker reports where available. Sparse recognition/export updates are supplemented by an approximate percentage (≈). Three compact columns show progress, elapsed time, and estimated time remaining in the current stage. Remaining time is calculated from smoothed real worker throughput and shown in coarse steps (for example, ~2 min, ~1.5 min, ~1 min), with hysteresis to avoid flicker near boundaries; a dash appears until measurements are available or when an old estimate expires. Interpolated percentages never complete a stage. WhisperKit's initial download shows received/total MB, followed by installation and Core ML preparation.

In Settings, choose **Word middle** (default) or **Whole word**. The choice applies to newly analyzed/imported media. Existing reviews and manual edits keep their timing. The selected sound mode is remembered across launches. Custom audio is copied into the app’s support folder, so moving or deleting the original cue does not lose it. A custom sound plays **once, in full, at its original speed**; speech resumes at the approved mute endpoint underneath any remaining sound tail. The cue never extends the mute interval. The end of the media still limits the output.

See the [macOS guide](macOS/README.md) for shortcuts, drafts, and development details.

## Recognition

One **Engine** picker selects the backend for the next file:

| Engine | Processing | Availability |
| --- | --- | --- |
| CPU · faster-whisper | Conventional CPU recognition, int8 | Included |
| Apple GPU · MLX | Metal GPU recognition, float16 | Apple Silicon; optional Python dependencies |
| WhisperKit · Experimental | Native Swift framework running converted Whisper weights through Core ML | Included; experimental |

CPU and MLX now offer a temporary **Model · testing** picker: **Large v3** (default, full model) or **Large v3 Turbo**. The choice applies to the next opened file and uses a separate recognition cache. WhisperKit currently keeps its pinned Large v3 Turbo weights. WhisperKit is an Argmax framework; its model is **not an Apple speech model** and must also be downloaded. It is not Apple's Speech framework. Native execution does not guarantee higher accuracy or model download availability.

The **Apple GPU · MLX / MPS** option also offers experimental **Parakeet v3**,
**Parakeet Ultra**, **Qwen3-ASR 1.7B**, and **GigaAM v3 RNNT**. Install their separate
runtime with `bash scripts/setup-experimental-gpu.sh`. The app selects
`.cache/asr-env/bin/python` automatically for these models unless a custom Python
executable is configured. The standard Whisper runtime remains in `.venv`.
Model weights download on first use only when downloads are enabled. The new
choices are GPU-only; unavailable GPU support produces an error without CPU
fallback. See [GPU comparison](experiments/gpu-models.md) for pinned weights,
timestamps, and the full-file benchmark command.

On the initial 19.93-second local reference using Turbo, MLX found 4/4 reviewed occurrences in three runs; CPU found 3/4; WhisperKit found 2/4, 3/4, and 3/4. This small sample is insufficient for a general quality ranking. WhisperKit remains experimental. See the [WhisperKit setup and reproducible benchmark](experiments/README.md).

```sh
.venv/bin/pip install -r requirements-whisperkit.txt
bash scripts/build-macos.sh --open
```

There is one app, **bleep.ly**, with CPU, MLX, and WhisperKit in the same Engine picker. The build always bundles the native WhisperKit helper; model weights are still downloaded only when requested. Choose WhisperKit and allow the initial download, or prepare the weights with `scripts/prepare-whisperkit.py`. The first Core ML preparation can take several minutes.

Upgrading removes the generated `build/bleep.ly Lab.app` after building the replacement. On first launch, the standard app imports missing settings, the saved custom sound, and the last review from Lab without overwriting existing standard-app data. Original Lab data stays intact; model caches already live in the shared repository.

## Exports

| App format | Result |
| --- | --- |
| **Audio Only** | 48 kHz, 24-bit stereo WAV; multiple processed tracks are mixed into one stereo track |
| **Video** | Original video stream copied without re-encoding; each processed audio track retained separately as AAC |

MOV, MP4, and MKV are supported output containers. A codec/container mismatch produces an error; there is no silent video re-encoding fallback. Subtitles, alternate video angles, and additional data streams are not preserved. Original recordings and existing outputs remain intact.

FCPXML and JSON export are available through the CLI; they are not app export options in this version.

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

Each successful app recognition now records one history row per audio track in
`тесты bleep.ly/recognition-history/runs.csv` inside the selected project folder.
It includes the exact model, engine/device, total and flagged word counts, source
hash, track index, elapsed analysis/inference time, and cache-hit status. A cache
hit has no inference time. WhisperKit uses automatic Core ML device selection;
it is not labelled as a GPU-only run. Counts measure flagged ASR tokens, not
verified profanity recall. JSON snapshots preserve all words and cache metadata;
each snapshot also has a word-level CSV. Repeated runs remain separate even if
they replace the same recognition cache. The matcher hash identifies which
dictionary/code produced the count. History is local and excluded from Git.

Import existing caches (safe to repeat; changed cache contents create another record):

```sh
.venv/bin/python scripts/import-recognition-history.py \
  --output 'тесты bleep.ly/recognition-history' \
  "$HOME/Library/Application Support/bleep.ly/cache" \
  "$HOME/Library/Application Support/bleep.ly Lab/cache"
```

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

Python integration tests generate short media with FFmpeg and check actual audio, independent track censorship, complete cue tails, video stream identity, cache behavior, and no-clobber exports. Swift tests cover the real Python bridge, native playback, automatic export, cancellation/Home, progress, context duration, and stable window layout. Native tests need a local macOS session with media services. Inference is mocked in regression tests; actual engine comparison is a separate offline benchmark.

Code lives in `censor/`, the SwiftUI app in `macOS/`, the experimental native helper in `experiments/WhisperKitRunner/`, and build tools in `scripts/`. Source media, transcripts, generated exports, weights, virtual environments, and caches are excluded from Git.

## Limitations

Recognition can miss words or place approximate boundaries, especially with music, overlapping voices, shouting, or fast speech. Review important material in Advanced and listen to the export. Muting affects the entire selected track, including music; this does not separate voices from a mixed recording. After analysis, **Preview with censorship** automatically prepares a temporary WAV using the export mixer. Original playback remains available while preparation runs; ready audio replaces it at the current position. The video is never copied or re-encoded. Completed Beep, Silence, and Custom variants are cached per track, so switching back does not render again. Edits or a changed custom cue require a new variant. The session retains up to eight recent variants and clears them on Home, a new source, or normal app exit; long WAV files can still use substantial disk space. The checkbox affects listening only; exports always apply the reviewed censoring. **Play export** opens the exported file.

The app is not notarized or distributed with a bundled Python runtime. Waveform zoom remains future work.
