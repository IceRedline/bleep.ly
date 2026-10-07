# Project workflow

- Use Git for version control in this project.
- Make a separate local commit after each completed implementation change and its relevant checks. Do not push unless requested.
- The user-selected reference for mute timing is `input_censored_reviewed.mov`, based on `input.reviewed.transcript.json` and `beep_trimmed.wav`. Preserve those intervals while allowing the full cue to play over resumed speech; keep these local media files intact.
- Preferred censoring: keep the approved partial-word mute/duck intervals unchanged. Play the complete selected sound once at original speed; no looping, stretching or trimming to word length. Speech resumes on the original schedule underneath any remaining sound tail. Never extend mute to fit the sound.
- Keep generated media, source recordings, transcripts, model caches and virtual environments out of Git.
