# CLI guide

[Back to README](../README.md)

**Contents:** [Usage](#usage) · [Review](#review) · [Matching](#matching) · [Timing](#timing) · [Speakers](#speakers) · [Final Cut Pro](#final-cut-pro) · [Cache](#cache)

## Usage

Activate the project's virtual environment or use `.venv/bin/python` explicitly:

```sh
export HF_HOME="$PWD/.cache/huggingface"
.venv/bin/python bleep.py input.mov --sound beep.wav --output output.mov \
  --language ru --model large-v3-turbo --backend faster-whisper
```

The default model is `large-v3-turbo`. Interactive runs without `--backend` offer MLX GPU or CPU (Enter selects CPU). Noninteractive runs default to CPU; transcript imports skip the choice. Downloads install weights locally and do not upload recordings. Use `--offline` after installation or supply a local model directory with `--model`.

MLX needs `requirements-mlx.txt`, Apple Silicon, and ARM64 Python. It uses Metal GPU, not the Neural Engine. `large-v3-turbo` resolves to `mlx-community/whisper-large-v3-turbo`; CTranslate2 weights cannot be reused. MLX supports float16/float32; CPU defaults to int8. Missing Metal produces an error instead of silently switching engines. Both pipelines use Silero VAD and map timestamps back to the source timeline; decoding settings differ.

For multiple audio streams, explicitly select `--audio-stream 0` (zero-based audio index). Only that processed track is exported. The first ordinary video stream is copied with `-c:v copy`; subtitles, other angles, and data streams are not carried over. MOV, MP4, and MKV outputs are supported. Incompatible containers fail without re-encoding video. Partial media outputs are removed. If one of two requested exports succeeds, it remains after a later export fails.

The default output is `input_censored.mov` plus `input.transcript.json`. Existing media, XML, and WAV directories are never overwritten. Transcript collisions receive `.1.json`, `.2.json`, etc. With no detected profanity the CLI saves the normal JSON/cache but creates no censored video or FCPXML. The desktop app can export an empty review.

## Review

```sh
.venv/bin/python bleep.py input.mov --dry-run
.venv/bin/python bleep.py input.mov --transcribe-only
```

`--dry-run` reads existing caches but writes no transcript, transcription cache, or media output. Temporary extracted audio is removed. A first model download still populates the model cache; use `--offline` to prevent it. `--transcribe-only` saves word timestamps and cache without needing a censor sound.

Progress is per stage: reading, audio extraction, recognition, and rendering. The terminal shows processed media time, elapsed time, and approximate ETA. Model loading and the first segment can leave the CLI at 0%; updates arrive with completed segments. The desktop additionally provides labeled estimates between sparse callbacks.

Reviewed JSON uses seconds from the first video frame, not editing timecode:

```json
{"words":[
  {"word":"ну","start":0.42,"end":0.58,"profane":false},
  {"word":"блядь","start":0.59,"end":0.91,"profane":true}
]}
```

Edit `profane`, `start`, and `end`, or add missing words. Numbers must be finite with `0 <= start < end <= duration`; `profane` must be a boolean.

```sh
.venv/bin/python bleep.py input.mov --from-transcript input.transcript.json \
  --sound beep.wav --output reviewed.mov
```

Import skips recognition and classification, preserving manual flags. It does not modify the supplied JSON; use `--transcript-output another.json` for a copy. Minimal JSON needs no metadata, so manually verify that it belongs to the source recording.

## Matching

`profanity.txt` has one word or stem per line. `--words blacklist.txt` replaces the default dictionary. Known Russian stems use bounded morphological families and whole-token matching. Normalization handles case, ё/е, accents, repeated letters, and hyphens. Arbitrary new entries match exactly; append `*` to explicitly allow prefix matching. `#` starts a comment.

There is no aggressive fuzzy matching: it increases false positives. Ordinary words such as `художник`, `страхуй`, `хлебать`, `учебник`, `ребёнок`, `корабля`, `бляшка`, and `колебание` are excluded by regression tests. The dictionary is not exhaustive; correct unknown recognition errors in JSON.

## Timing

- `--censor-style middle` is the CLI default: mute the middle 60% of a word, capped by the primary cue duration. It is partial censorship. Padding and merge-gap do not apply here; overlapping annotations merge and are capped again.
- `--censor-style full` mutes the word with default padding of 50 ms before and 80 ms after. Adjust `--padding-before`, `--padding-after`, and `--merge-gap` (default 20 ms). Intervals are clipped to the media boundaries.
- `--mode mute` removes the original sound within each interval; `--mode duck --duck-db -30` reduces it by 30 dB.
- Linear 7 ms fades sit outside mute boundaries to avoid clicks. Timing rounds to the nearest 48 kHz sample.
- Each merged interval triggers one complete cue at original speed, without looping, stretching, or trimming to word length. The mute endpoint stays fixed while speech resumes underneath the tail. Neighboring tails may overlap. The media end limits the export.

The desktop uses a fixed 0.383021-second cap for its default middle-word timing, based on the approved `beep_trimmed.wav` reference; changing sounds never recalculates reviewed mute intervals. Desktop whole-word mode uses exact recognized boundaries without the CLI's padding defaults.

Audio delays relative to video are preserved; short tracks are padded with silence. Output audio is stereo. A limiter controls render peaks without automatic gain. Adjust unusually quiet/loud cue files before processing. Muting also affects music/background sound in the selected track; no voice isolation is performed.

## Speakers

Optional speaker labeling applies to a mixed audio track. It does not extract individual voices into separate tracks. Whisper recognizes words; sherpa-onnx CPU runs Pyannote segmentation 3.0 and 3D-Speaker ERes2Net to assign speakers. MLX only accelerates recognition.

```sh
.venv/bin/pip install -r requirements-speakers.txt
mkdir -p .cache/speaker-models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 \
  -o .cache/speaker-models/segmentation.tar.bz2
tar -xjf .cache/speaker-models/segmentation.tar.bz2 -C .cache/speaker-models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
  -o .cache/speaker-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
.venv/bin/python bleep.py input.mov --from-transcript input.transcript.json \
  --speaker-reference 24 52 --num-speakers 4 \
  --sound beep.wav --sound-others others.wav --output two_sounds.mov
```

`--speaker-reference START END` identifies seconds **in this recording** containing only your voice. The default speaker count is four. Each recording needs its own reference; no persistent voice profile or external voice sample is used. `--speaker-model-dir` selects another model directory. `--speaker-segments segments.json` can supply existing segments alongside the reference: `[{"start":0,"end":2,"speaker":0}]`.

The saved JSON adds `speaker` (`me`, `others`, or `unknown`) and `speaker_coverage`, a time-coverage ratio, **not identity confidence**. Ambiguous/overlapping speech uses `unknown` and the primary sound; it is not skipped. Merged intervals with conflicting labels are ambiguous. Both cues play in full without changing the existing mute intervals.

Correct `speaker` manually and rerender with `--from-transcript` **without** `--speaker-reference` to preserve those corrections. `--transcribe-only` supports speaker labeling without rendering. Noise, similar voices, and overlap can cause incorrect clustering. After changing models, regenerate labels without stale `--speaker-segments`.

## Final Cut Pro

```sh
.venv/bin/python bleep.py input.mov --sound beep.wav --fcpxml censor.fcpxml
.venv/bin/python bleep.py input.mov --from-transcript input.transcript.json \
  --sound beep.wav --mode duck --duck-db -30 --fcpxml reviewed.fcpxml
.venv/bin/python bleep.py input.mov --sound beep.wav --output output.mov --fcpxml censor.fcpxml
```

The first command exports FCPXML 1.10 and a sibling `censor_media/` directory, without rendering a new video. Import via **File → Import → XML**. The primary storyline uses original video with embedded audio disabled. A connected audio clip on lane −1 contains `original_censored.wav`; individual full-length cues occupy lower lanes, using separate lanes when tails overlap. All helper WAVs are PCM 24-bit, 48 kHz stereo. Speaker-specific cues are supported.

Mute/duck is baked into the bed WAV, not volume automation. Moving a cue in Final Cut does not move its mute interval; edit JSON and export again to change that. The video render's master limiter is not reproduced in XML, so check summed levels in Final Cut.

Timing uses rational values, sample-aligned audio, and whole-frame storyline duration. Source timecode and 29.97/59.94 drop-frame are handled. Variable-frame-rate, unusual timecode, rotated/anamorphic video, and complex HDR projects need manual validation or a CFR export first. This processes a finished recording and does not reconstruct its original multiclip project.

Media references are absolute. Keep the source and `_media` directory until import/consolidation. The output is `.fcpxml`, not an `.fcpxmld` bundle. XML has been checked against Apple's 1.10 DTD; actual Final Cut GUI import has not been verified in this environment.

```sh
xmllint --noout --dtdvalid /path/to/FCPXMLv1_10.dtd censor.fcpxml
```

## Cache

Default CLI location: `<source folder>/.cache/auto-censor/<hash>.json`; override with `--cache-dir`. Keys include SHA-256 of the entire source, model, language, compute type, selected audio stream, backend version, and recognition settings. Local model file sizes/mtime contribute to identity. Hashing large media still reads the whole file on a cache hit.

Caches store raw timestamps; dictionary and timing changes apply without rerunning recognition. Manual edits only enter through `--from-transcript`. Corrupt caches are ignored with a warning. Speaker caches separately include audio, weights, engine version, and speaker count. Model downloads use a separate Hugging Face cache configured with `HF_HOME`.

Use `--verbose` for diagnostics. Whisper timestamps are estimates; music, noise, overlap, whispers, and fast speech can cause misses or shifted boundaries. Review the final output.
