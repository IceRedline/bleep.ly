<p align="center"><img src="icon.PNG" alt="bleep.ly icon" width="128"></p>

# bleep.ly

Local speech recognition and profanity censoring for Russian video and audio. A native **macOS app** wraps the Python engine with drag and drop, a review timeline, and clean audio/video export. Your recordings stay on your Mac.

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

- **Fast Mode:** select Beep, Silence, or custom audio, then drop a file. Recognition and export run automatically. The result is saved beside the source as `NAME_censored.ext`; existing files receive a numbered alternative and are never overwritten.
- **Advanced:** review detections on the timeline, uncheck false positives, flag other transcript words, add missing intervals, and adjust mute boundaries. `⌘Z` undoes review edits. **Listen in Context** plays the word with **0.2 seconds before and 0.2 seconds after**, clipped at the file boundaries.
- **Multiple audio tracks:** both modes analyze each track independently. Advanced shows separate timeline rows and a track selector for listening and editing. Video export preserves separate processed audio tracks.
- **Home:** click the logo, the Home button, or press `⌘⇧H`. During processing this cancels the worker and returns to file selection. **Resume Last Review** restores the latest autosaved review.

The drop target stays in place when switching modes; controls below it fade. The window background extends behind the native traffic lights and changes color with the processing stage.

Stage progress uses worker reports where available. Sparse recognition/export updates are supplemented by a visibly labeled **Estimated** percentage and elapsed time; estimates cannot complete a stage. WhisperKit's initial download shows received/total MB, followed by installation and Core ML preparation.

In Settings, choose **Word middle** (default) or **Whole word**. The choice applies to newly analyzed/imported media. Existing reviews and manual edits keep their timing. A custom sound plays **once, in full, at its original speed**; speech resumes at the approved mute endpoint underneath any remaining sound tail. The cue never extends the mute interval. The end of the media still limits the output.

See the [macOS guide](macOS/README.md) for shortcuts, drafts, and development details.

## Recognition

One **Engine** picker selects the backend for the next file:

| Engine | Processing | Availability |
| --- | --- | --- |
| CPU · faster-whisper | Conventional CPU recognition, int8 | Standard app and Lab |
| Apple GPU · MLX | Metal GPU recognition, float16 | Apple Silicon; optional Python dependencies |
| WhisperKit · Experimental | Native Swift framework running converted Whisper weights through Core ML | Separate Lab build only |

All three use the Whisper large-v3-turbo family with different runtime/decoding configurations and separate caches. WhisperKit is an Argmax framework; its model is **not an Apple speech model** and must also be downloaded. It is not Apple's Speech framework. Native execution does not guarantee higher accuracy or model download availability.

On the initial 19.93-second local reference, MLX found 4/4 reviewed occurrences in three runs; CPU found 3/4; WhisperKit found 2/4, 3/4, and 3/4. This small sample is insufficient for a general quality ranking. WhisperKit remains experimental. See the [Lab setup and reproducible benchmark](experiments/README.md).

```sh
.venv/bin/pip install -r requirements-whisperkit.txt
bash scripts/build-macos.sh --whisperkit --open
```

Lab has independent settings, drafts, and transcript caches. Choose WhisperKit in its Engine picker and allow the initial download, or prepare the weights with `scripts/prepare-whisperkit.py`. The first Core ML preparation can take several minutes.

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

```sh
.venv/bin/python -m unittest discover -s tests -q
CLANG_MODULE_CACHE_PATH="$PWD/.cache/clang" \
SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.cache/clang" \
swift test --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
```

Python integration tests generate short media with FFmpeg and check actual audio, independent track censorship, complete cue tails, video stream identity, cache behavior, and no-clobber exports. Swift tests cover the real Python bridge, native playback, automatic export, cancellation/Home, progress, context duration, and stable window layout. Native tests need a local macOS session with media services. Inference is mocked in regression tests; actual engine comparison is a separate offline benchmark.

Code lives in `censor/`, the SwiftUI app in `macOS/`, the experimental native helper in `experiments/WhisperKitRunner/`, and build tools in `scripts/`. Source media, transcripts, generated exports, weights, virtual environments, and caches are excluded from Git.

## Limitations

Recognition can miss words or place approximate boundaries, especially with music, overlapping voices, shouting, or fast speech. Review important material in Advanced and listen to the export. Muting affects the entire selected track, including music; this does not separate voices from a mixed recording. The in-app player previews original audio; **Play export** opens the processed result.

The app is not notarized or distributed with a bundled Python runtime. Waveform zoom and processed playback inside the review editor remain future work.
