# Unreleased

- Add overlapping context to GigaAM recognition windows and reconcile boundary words, preventing words split at a VAD chunk boundary from disappearing. Invalidate older GigaAM recognition caches; saved reviews and manual mute intervals remain unchanged.
- Stream desktop export mixing in one-second blocks instead of building a full-length delayed audio branch for every censor interval. Only active mute envelopes and custom-sound tails are mixed, keeping memory bounded on long recordings with hundreds of detections.
- Preserve the approved sample timing, complete custom cues, overlapping fades, stereo audio, limiter behavior, independent video audio tracks, and video stream copying. Single-track WAV export writes directly to its atomic destination without a full-length intermediate audio file.
