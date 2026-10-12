# Unreleased

- Stream desktop export mixing in one-second blocks instead of building a full-length delayed audio branch for every censor interval. Only active mute envelopes and custom-sound tails are mixed, keeping memory bounded on long recordings with hundreds of detections.
- Preserve the approved sample timing, complete custom cues, overlapping fades, stereo audio, limiter behavior, independent video audio tracks, and video stream copying. Single-track WAV export writes directly to its atomic destination without a full-length intermediate audio file.
