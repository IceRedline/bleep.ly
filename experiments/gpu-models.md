# Experimental Apple GPU models

Select **Apple GPU · MLX / MPS → Model · testing** in the single bleep.ly app.
The default remains Whisper Large v3. Experimental choices share the existing
profanity filter, review editor, audio preview and export code. Existing reviewed
mute intervals and cue playback rules are unchanged.

## Installation and assets

```sh
bash scripts/setup-experimental-gpu.sh
bash scripts/build-macos.sh
```

Dependencies are isolated in `.cache/asr-env`; Whisper still runs in `.venv`.
A custom Python executable in Settings overrides automatic runtime selection
and must have the experimental dependencies installed. Weights stay under
`.cache/huggingface` and `.cache/gigaam`, never in Git. Enable first-time model
downloads in Settings for missing weights; subsequent runs can stay offline.

| Choice | Weights | Runtime / precision | Word timestamps |
| --- | --- | --- | --- |
| Parakeet v3 | [mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3), `ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15` | parakeet-mlx 0.5.3 / BF16 / Metal | SentencePiece pieces merged into words |
| Parakeet Ultra | [selcukkubur/parakeet-ultra-mlx](https://huggingface.co/selcukkubur/parakeet-ultra-mlx), `b554592c50b2a48471add2daa3d46fa9f00fef5e` | parakeet-mlx 0.5.3 / BF16 / Metal | Same adapter as v3 |
| Qwen3-ASR 1.7B | [Qwen/Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), `7278e1e70fe206f11671096ffdd38061171dd6e5` | mlx-qwen3-asr 0.4.4 / FP16 / Metal | Native MLX Qwen3-ForcedAligner-0.6B, `c7cbfc2048c462b0d63a45797104fc9db3ad62b7` |
| GigaAM v3 | Official `v3_e2e_rnnt`, checkpoint MD5 `2730de7545ac43ad256485a462b0a27a` | GigaAM `7447938d791c4f3e643386ee22c33777004293a5`, torch/torchaudio 2.11 / MPS; FP32 weights with FP16 encoder autocast | Official RNNT token-to-word timestamps |

Ultra uses a community format conversion of Moondream's weights. Its results
measure this specific conversion/runtime, not the upstream NVIDIA/Photon pipeline.
The original Ultra model's VAD head is not used by this MLX adapter.

Parakeet uses 120-second chunks with 15-second overlap and the library's overlap
merge. Its tokens must be joined before counting profanity; counting subword
tokens directly would inflate word counts and miss split profanity.
Qwen uses the runtime's approximately 30-second low-energy chunk boundaries,
forced Russian, greedy decoding, and its separate GPU aligner. Generation hitting
the token limit is an error rather than an accepted partial transcript.
GigaAM uses Silero VAD with a 20-second maximum speech chunk and maps each result
to the original recording. This avoids the optional gated pyannote longform
dependency. GigaAM requests MPS explicitly with operator CPU fallback disabled.
Audio decoding, VAD and bookkeeping can still use CPU, as in the Whisper pipeline.

## Full-file comparison

```sh
HF_HOME="$PWD/.cache/huggingface" HF_HUB_DISABLE_TELEMETRY=1 \
  .cache/asr-env/bin/python scripts/benchmark-gpu-models.py 'стрим.m4v' \
  --prepare --output 'тесты bleep.ly/gpu-comparison-new'
```

Downloads finish before timing. The script then runs all four experimental
choices and Whisper Turbo sequentially, in separate processes, with network
access disabled and transcription cache bypassed. Use `--models` to choose a
subset or include `large-v3`. Do not run heavy applications or compilation while
measuring. Use a new output directory for a new experiment; existing per-model
results are retained when resuming an interrupted batch.

`summary.csv` contains each success/error and wall time. Successful results also
append to `тесты bleep.ly/recognition-history/runs.csv`. Requests, progress events,
stderr and review JSON remain beside the summary. Wall time includes Python
startup, audio extraction, model loading and recognition/alignment. It excludes
downloads. Model loading and first-use kernel compilation are included; these
are single-run measurements, not steady-state throughput benchmarks.

Total word count and profanity count do not measure accuracy. Different token
boundaries, omissions, repetitions and false positives can all change counts.
Quality decisions require manually reviewed occurrences and audio boundaries,
including samples where every model missed a word. Comparing pipelines here also
compares their segmentation and decoding settings, not only model weights.

## Local full-file run · 2026-10-10

Apple M3 Pro, 36 GiB RAM; one 27:44 recording, sequential fresh processes,
no transcript cache reuse. All models used Apple GPU (MLX Metal or PyTorch MPS).
Downloads and the earlier 25-second compatibility checks preceded measurement.

| Model | ASR words | Flagged words | Wall time |
| --- | ---: | ---: | ---: |
| Parakeet v3 | 3494 | 350 | 43.92 s |
| Parakeet Ultra (community MLX conversion) | 3124 | 352 | 39.17 s |
| Qwen3-ASR 1.7B + aligner | 3251 | 279 | 283.14 s |
| GigaAM v3 e2e RNNT | 3871 | 416 | 76.54 s |
| Whisper Large v3 Turbo | 3510 | 332 | 144.54 s |

Artifacts are in the ignored `тесты bleep.ly/gpu-benchmark-2026-10-10/full/`.
`time-windows.csv` compares counts by recording interval.
`gigaam-review-candidates.csv` lists 105 GigaAM findings with no Turbo flagged-word
center within 0.6 seconds; these are review candidates, not confirmed extra hits.
No reviewed ground truth exists for this full recording, so no recall/precision
or winner on accuracy is claimed. Parakeet timestamps sometimes cover a long
interval (the first flagged word spans about a second); audible censor quality
must be checked separately. The default model was not changed.
