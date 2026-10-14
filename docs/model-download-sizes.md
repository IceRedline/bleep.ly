# Model download sizes

Verified from publisher file metadata on October 14, 2026. Decimal GB (1 GB = 1,000,000,000 bytes). These are complete model sizes before cache reuse; the UI rounds upward to 0.1 GB. No model weights were downloaded for this check.

| Asset | Bytes | Repository / revision |
| --- | ---: | --- |
| CPU Large v3 | 3,090,835,702 | Systran/faster-whisper-large-v3 / edaa852ec7e145841d8ffdb056a99866b5f0a478 |
| CPU Turbo | 1,621,665,983 | mobiuslabsgmbh/faster-whisper-large-v3-turbo / 0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf |
| MLX Large v3 | 3,083,520,685 | mlx-community/whisper-large-v3-mlx / 49e6aa286ad60c14352c404340ded53710378a11 |
| MLX Turbo | 1,613,977,880 | mlx-community/whisper-large-v3-turbo / a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb |
| parakeet-v3 | 2,509,041,541 | mlx-community/parakeet-tdt-0.6b-v3 / ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15 |
| parakeet-ultra | 1,254,937,267 | selcukkubur/parakeet-ultra-mlx / b554592c50b2a48471add2daa3d46fa9f00fef5e |
| qwen3-asr | 4,703,055,333 | Qwen/Qwen3-ASR-1.7B / 7278e1e70fe206f11671096ffdd38061171dd6e5 |
| aligner | 1,840,013,484 | Qwen/Qwen3-ForcedAligner-0.6B / c7cbfc2048c462b0d63a45797104fc9db3ad62b7 |
| WhisperKit | 1,626,165,383 | argmaxinc/whisperkit-coreml / 0f63a7800b00dd0226abd051b906c246e1907482 |
| WhisperKit tokenizer | 2,993,180 | openai/whisper-large-v3-turbo / 41f01f3fe87f28c78e2fbf8b568835947dd65ed9 |
| v3_e2e_rnnt.ckpt | 448,929,252 | https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM/v3_e2e_rnnt.ckpt / CDN Content-Length |
| v3_e2e_rnnt_tokenizer.model | 255,336 | https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM/v3_e2e_rnnt_tokenizer.model / CDN Content-Length |

Qwen3-ASR and GigaAM both require the 1,840,013,484-byte Qwen ForcedAligner. WhisperKit includes its tokenizer. Estimates include every file matching the actual backend filters. Previously cached files may reduce transfer size; temporary installation files need additional space.

Update `ModelDownloadEstimate.swift` when changing model repositories, revisions, filters or required components. Whisper CPU/MLX repositories currently follow their upstream default revision, so their displayed sizes are approximate.
