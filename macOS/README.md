# bleep.ly for macOS

Native SwiftUI front end for the Python engine. The signed, Apple-notarized
[0.1.2 release](https://github.com/IceRedline/bleep.ly/releases/tag/v0.1.2) supports
**Apple Silicon and macOS 15.0 or later**. It includes Python, FFmpeg and the
recognition engines; only model weights download separately. Install it by
dragging **bleep.ly** from the DMG to **Applications**.

The instructions below describe development builds. The Swift app targets
macOS 14+; its included WhisperKit helper requires Swift 5.10 or later. Use
Xcode, Python 3.11 and FFmpeg 8. GPU Python dependencies can require a newer OS
than the Swift app target; see the [release guide](../scripts/release/README.md)
for the pinned macOS 15 build. Exports are **Audio Only** (48 kHz, 24-bit stereo
WAV) and **Video** (original video stream + AAC audio, no video re-encoding).

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
brew install ffmpeg@8
brew link --force ffmpeg@8
# Optional: existing Apple GPU engine
.venv/bin/pip install -r requirements-mlx.txt
```

With no saved preferences, the development app uses the project's `.venv/bin/python`, CPU/faster-whisper, full `large-v3`, and Russian speech. The temporary **Model · testing** picker selects Large v3 or Large v3 Turbo for CPU and MLX. WhisperKit keeps its pinned Turbo model. Selection applies to new files, and each model has a separate recognition cache. Large v3 has its own initial download. Choose **Apple GPU · MLX / MPS** in Settings to use the existing MLX implementation. The same app includes **WhisperKit · Experimental** in the Engine picker; see [WhisperKit setup](../experiments/README.md). Model downloads are disabled by default; enable **Allow first-time model download** if your chosen engine's model is not cached. The app reuses the repository’s `.cache/huggingface` model cache (or an explicitly inherited `HF_HOME`). Recognition happens locally with every engine. No recording is uploaded.

Changing **Video language** selects a model preset: Russian selects GigaAM v3
on Apple Silicon; English selects Whisper Large v3 Turbo and retains CPU if it
was already selected. Selecting the same language or relaunching preserves
manual model choices. GigaAM is unavailable for English. The GPU picker also
includes Parakeet v3, Parakeet Ultra and Qwen3-ASR 1.7B. For development, install
their separate runtime with `bash scripts/setup-experimental-gpu.sh`; release
DMGs already contain it. See [recognition options](../README.md#recognition).

Release builds store models in
`~/Library/Application Support/bleep.ly/models/` and recognition history in
`~/Library/Application Support/bleep.ly/recognition-history/`. Development
builds use the repository's `.cache/` for models and
`тесты bleep.ly/recognition-history/` for history.

## Fast Mode and Advanced Mode

The header switches between **Fast Mode** (the initial default) and **Advanced**; your choice is remembered. Both use the same local recognition engine and censoring preference. Fast Mode does not reduce recognition quality.

In **Fast Mode**, choose a censor sound if needed, then drop your media. After recognition, video sources offer **Save as Video** as the primary action and **Save as Audio** as the secondary action. Audio-only sources offer just **Save as Audio**. Each button opens a save dialog with its format already selected; no file is exported until you confirm a destination. The dialog initially suggests the source folder and an unused `NAME_censored.ext` filename. Video retains the source MOV/MP4/MKV container by default (otherwise MKV); audio becomes WAV. Existing files are never overwritten. After saving, the selected path is shown and both applicable save actions remain available, so you can export the other format without repeating recognition. Cancelling the dialog keeps the analyzed result; a failed export can be retried. Use the header's Advanced selector to inspect intervals, or Home/Open for another file.

In **Advanced Mode**, analysis stops at the timeline for manual review. Switching modes does not rerun recognition or discard edits. On the welcome screen the drop target stays fixed while the controls below fade. Click the logo, Home, or ⌘⇧H to cancel any active operation and return to file selection; the autosaved review can be resumed. The colored window background continues behind the native traffic lights. Resuming a saved review or importing a reviewed transcript always opens Advanced. The steps below describe Advanced Mode.

## Workflow

1. Drop a single video/audio file or choose **Open Media…** (⌘O).
2. Follow stage progress. Sparse recognition/export callbacks are supplemented by an approximate percentage (≈), elapsed time, and estimated stage time remaining in three compact columns. ETA smooths real worker throughput and uses coarse steps with hysteresis (~2 min, ~1.5 min, ~1 min); a dash appears while unavailable; interpolated percentages never reach 100%. Model initialization remains indeterminate. Cancel stops the Python process group and FFmpeg children.
3. Choose Beep, Silence, or Custom on the welcome screen before loading media. **Preview with censorship** is enabled by default. Advanced opens the original immediately after analysis and prepares censored audio in the background. You can play and seek during preparation; when ready, the player switches audio at the current position and preserves playback. Click a word or timeline marker to hear 0.2 seconds before the word and 0.2 seconds after it. A temporary WAV uses the export mixer, without re-encoding video or rerunning recognition. Completed sound variants are cached per track, so returning to Beep/Silence/Custom skips preparation. Word edits and timing changes update only affected audio windows, including overlapping intervals, fades, and full cue tails. Source audio is decoded once per track in the session. Undo reuses a matching cached version or applies local patches. The prepared preview keeps playing during updates, and the new version takes over at the current position. A different custom cue prepares its own variant. Review Words follows playback with a smooth native scroll (respecting Reduce Motion), scrolling to and highlighting the latest censored word on the selected track. Seeking recalculates that selection; Listen in Context keeps the clicked word selected during its pre-roll. Turning the checkbox off returns to the original. Export always applies censorship; **Play export** opens the saved result.
4. Uncheck false positives; use **All words** to flag a missed transcript word. **Add interval** handles words absent from the transcript. The timing button edits exact mute boundaries in seconds. ⌘Z undoes up to 100 review edits.
Unchecked words remain in **Flagged** with **Censoring off**, so you can enable them again directly. This list membership is saved in the review draft; the header shows the number of candidates separately from the number selected for censorship. Words manually selected from **All words** also remain in the review list after unchecking.

5. Pick **Beep**, **Silence**, or drop/choose custom audio. The full custom cue plays once at original speed. Speech resumes at the same approved mute endpoint, even while a cue tail is still playing. A cue is only cut by the end of the entire media, not by word length. Overlapping mute ranges form one interval with one cue.
6. Choose **Audio Only** or **Video**, then **Export** (⌘E). Existing files are never overwritten; choose another filename. For a codec/container mismatch, try MOV or MKV. There is no silent fallback to video re-encoding.

In Settings → Censoring, choose **Word middle (default)** or **Whole word**. The choice applies when opening media, including imported transcripts, and is saved with the review. Whole word uses the exact recognized word boundaries, without a cap tied to cue length. Existing reviews and manual edits are not recalculated. Recognition caches are reused across both styles.

Default automatic mute intervals use the same middle-word rule and 0.383021s cap as the approved `beep_trimmed.wav` reference. Switching sounds does not recalculate these intervals. Manual intervals use your exact boundaries. The original CLI and local reviewed media remain untouched.

Reviews autosave to `~/Library/Application Support/bleep.ly/last-review.json`; **Resume Last Review** reopens the latest successful review. Word timestamps and classifications are cached separately under `cache/` in that folder. The last review is replaced when a new source finishes analysis. Clicking **Custom** activates the saved custom sound immediately. If no sound has been saved yet, it opens the audio file chooser; cancelling or a failed import keeps the previous selection. Click the filename below the sound selector to choose a replacement, or drop a new sound there. Cancelling replacement keeps the current mode and saved sound. The sound mode and custom audio are retained across launches. Custom audio is copied into `Custom Sounds/` in the app support directory; it remains available if the original cue is moved or deleted. Replacing it keeps only the new saved copy. Export checks source size/modification time and refuses changed media. Preview audio is a temporary session cache of decoded source audio and up to eight recent variants, cleared on Home, a new source, or normal app exit. APFS snapshots use copy-on-write so small edits do not copy an entire long WAV; other filesystems fall back to a file copy, but still process only the changed audio windows. It contains audio only, though long uncompressed WAV files can still be large.

**Import Reviewed Transcript…** reuses an existing word-level transcript for the currently opened source, with its manual flags preserved and no inference. This is also available after an analysis error. It derives the initial middle-word intervals using the approved cap. It does not modify the supplied transcript.

Recognition caches belong to an app build and installation. Normal relaunches
reuse them; a new build or a reinstallation (including the same version) requires
fresh recognition when media is opened again. Both development and release
packaging generate a new build identifier. Downloaded models, recognition history,
and the last saved review are retained. **Resume Last Review** deliberately keeps
manual work; reopen the source to apply recognition fixes from an update.

Files with multiple audio tracks are analyzed independently in both modes. Advanced shows a timeline row for each track; select a row or use the track picker to listen and edit that track. Video exports keep the processed audio tracks separate. Audio Only mixes them into one stereo WAV. Import Reviewed Transcript applies to the selected track when multiple tracks are present. For audio-only sources the Video option is hidden. An empty/no-profanity review can still be exported.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -q
CLANG_MODULE_CACHE_PATH="$PWD/.cache/clang" \
SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.cache/clang" \
swift test --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
```

The Python integration tests cover audio inputs, silence, cue tails, no-clobber exports, zero findings, edited intervals, cache reuse, the JSON protocol, and video stream identity. When the local approved reference is available its mute intervals are compared exactly. Swift tests cover protocol decoding/encoding, manual-interval validation, real Swift → Python → WAV export, cancellation of a worker group, and native view rendering for visual review. Workflow tests wait for explicit save choices, export both formats from one analysis, cancel the save dialog, preserve existing files, check preferences and edits, retry failures, and cancel before processing. Video regression tests load a generated MOV, check seeking and screen transitions, and verify that the standalone executable links AVKit (the XCTest host can otherwise mask a missing framework). Run these tests from a local macOS session with access to native media decoding services.

## Structure

- `Sources/Bleep/ContentView.swift`: drop zone, stage colors, review/timeline, interval editing, export controls. Reduced Motion disables background animation; Reduced Transparency reduces the glow.
- `Sources/Bleep/AppModel.swift`: review state, native player, autosave, file panels, undo.
- `Sources/Bleep/PythonBridge.swift`: asynchronous `Process` execution without a shell, JSON-lines events, error capture, cancellation.
- `../censor/desktop.py`: version 1 JSON request/event protocol, using the existing recognition, profanity matching, and mixing functions.

FCPXML/JSON export and waveform zoom are left for subsequent versions. Release DMGs include Python and FFmpeg; see [release instructions](../scripts/release/README.md). The CLI's existing FCPXML features remain available independently.

There is no separate Lab app. The unified build uses `ly.bleep.desktop` and the regular app support directory. On first launch it copies missing settings, the saved custom cue, and the last review from the former Lab app; existing regular-app data and the original Lab files are preserved.
