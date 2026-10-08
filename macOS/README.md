# bleep.ly for macOS

Native SwiftUI front end for the existing Python engine. macOS 14+, Xcode/Swift 5.9+, Python 3.11+, and FFmpeg. The first version exports **Audio Only** (48 kHz, 24-bit stereo WAV) and **Video** (original video stream + AAC audio, no video re-encoding).

## Build and launch

From the repository root:

```sh
./scripts/build-macos.sh --open
```

This builds `build/bleep.ly.app` with a local ad-hoc signature. You can open that app from Finder afterwards. `macOS/Package.swift` can also be opened in Xcode. When running through Xcode, set the project folder in the app's Settings.

This is a local developer app: Python, FFmpeg, models, and the repository are external dependencies, not bundled. It is not notarized or ready for App Store distribution. Moving the app is fine as long as its project folder remains accessible; moving the repository requires updating Settings or rebuilding.

Set up the engine once if it is not already installed:

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
brew install ffmpeg
# Optional: existing Apple GPU engine
.venv/bin/pip install -r requirements-mlx.txt
```

The app defaults to the project's `.venv/bin/python`, CPU/faster-whisper, `large-v3-turbo`, and Russian speech. Choose **Apple GPU · MLX** in Settings to use the existing MLX implementation. The separate Lab build adds WhisperKit to the same Engine picker; see [WhisperKit Lab](../experiments/README.md). Model downloads are disabled by default; enable **Allow first-time model download** if your chosen engine's model is not cached. The app reuses the repository’s `.cache/huggingface` model cache (or an explicitly inherited `HF_HOME`). Recognition happens locally in both cases. No recording is uploaded.

## Fast Mode and Advanced Mode

The header switches between **Fast Mode** (the initial default) and **Advanced**; your choice is remembered. Both use the same local recognition engine and censoring preference. Fast Mode does not reduce recognition quality.

In **Fast Mode**, choose a censor sound if needed, then drop your media. Recognition and export run automatically without a review or save dialog. Video stays video (MOV/MP4/MKV source container, otherwise MKV); audio becomes WAV. The output is saved beside the source as `NAME_censored.ext`, then `NAME_censored_2.ext`, etc. Existing files are never overwritten. The completion screen offers playback, Finder, another file, or **Review in Advanced Mode**. If export fails (for example the source folder is read-only), the review remains available; retry or use **Save as…** without repeating recognition. Cancel stops the current operation. Automatic detection can miss words; use Advanced when you want to verify each interval.

In **Advanced Mode**, analysis stops at the timeline for manual review. Switching modes does not rerun recognition or discard edits. On the welcome screen the drop target stays fixed while the controls below fade. Click the logo, Home, or ⌘⇧H to cancel any active operation and return to file selection; the autosaved review can be resumed. The colored window background continues behind the native traffic lights. Resuming a saved review or importing a reviewed transcript always opens Advanced. The steps below describe Advanced Mode.

## Workflow

1. Drop a single video/audio file or choose **Open Media…** (⌘O).
2. Follow stage progress. Sparse recognition/export callbacks are supplemented by a labeled Estimated percentage and elapsed time; estimates never reach 100%. Model initialization remains indeterminate. Cancel stops the Python process group and FFmpeg children.
3. Click a word or timeline marker to hear its original context (0.2 seconds before, 0.2 seconds after). The main player previews the original media, clearly labeled in the interface. The exported file is the processed preview; use **Play export** afterwards.
4. Uncheck false positives; use **All words** to flag a missed transcript word. **Add interval** handles words absent from the transcript. The timing button edits exact mute boundaries in seconds. ⌘Z undoes up to 100 review edits.
5. Pick **Beep**, **Silence**, or drop/choose custom audio. The full custom cue plays once at original speed. Speech resumes at the same approved mute endpoint, even while a cue tail is still playing. A cue is only cut by the end of the entire media, not by word length. Overlapping mute ranges form one interval with one cue.
6. Choose **Audio Only** or **Video**, then **Export** (⌘E). Existing files are never overwritten; choose another filename. For a codec/container mismatch, try MOV or MKV. There is no silent fallback to video re-encoding.

In Settings → Censoring, choose **Word middle (default)** or **Whole word**. The choice applies when opening media, including imported transcripts, and is saved with the review. Whole word uses the exact recognized word boundaries, without a cap tied to cue length. Existing reviews and manual edits are not recalculated. Recognition caches are reused across both styles.

Default automatic mute intervals use the same middle-word rule and 0.383021s cap as the approved `beep_trimmed.wav` reference. Switching sounds does not recalculate these intervals. Manual intervals use your exact boundaries. The original CLI and local reviewed media remain untouched.

Reviews autosave to `~/Library/Application Support/bleep.ly/last-review.json`; **Resume Last Review** reopens the latest successful review. Word timestamps and classifications are cached separately under `cache/` in that folder. The last review is replaced when a new source finishes analysis. Sound selection is per session. Export checks source size/modification time and refuses changed media.

**Import Reviewed Transcript…** reuses an existing word-level transcript for the currently opened source, with its manual flags preserved and no inference. This is also available after an analysis error. It derives the initial middle-word intervals using the approved cap. It does not modify the supplied transcript.

Files with multiple audio tracks are analyzed independently in both modes. Advanced shows a timeline row for each track; select a row or use the track picker to listen and edit that track. Video exports keep the processed audio tracks separate. Audio Only mixes them into one stereo WAV. Import Reviewed Transcript applies to the selected track when multiple tracks are present. For audio-only sources the Video option is hidden. An empty/no-profanity review can still be exported.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -q
CLANG_MODULE_CACHE_PATH="$PWD/.cache/clang" \
SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.cache/clang" \
swift test --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
```

The Python integration tests cover audio inputs, silence, cue tails, no-clobber exports, zero findings, edited intervals, cache reuse, the JSON protocol, and video stream identity. When the local approved reference is available its mute intervals are compared exactly. Swift tests cover protocol decoding/encoding, manual-interval validation, real Swift → Python → WAV export, cancellation of a worker group, and native view rendering for visual review. Workflow tests run automatic video/audio export, preserve existing files, check preferences and edits, retry failures, and cancel before processing. Video regression tests load a generated MOV, check seeking and screen transitions, and verify that the standalone executable links AVKit (the XCTest host can otherwise mask a missing framework). Run these tests from a local macOS session with access to native media decoding services.

## Structure

- `Sources/Bleep/ContentView.swift`: drop zone, stage colors, review/timeline, interval editing, export controls. Reduced Motion disables background animation; Reduced Transparency reduces the glow.
- `Sources/Bleep/AppModel.swift`: review state, native player, autosave, file panels, undo.
- `Sources/Bleep/PythonBridge.swift`: asynchronous `Process` execution without a shell, JSON-lines events, error capture, cancellation.
- `../censor/desktop.py`: version 1 JSON request/event protocol, using the existing recognition, profanity matching, and mixing functions.

FCPXML/JSON export, a packaged Python runtime, waveform zoom, and a processed in-app preview are left for subsequent versions. The CLI's existing FCPXML features remain available independently.
