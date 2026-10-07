# Project workflow

- Use Git for version control in this project.
- Make a separate local commit after each completed implementation change and its relevant checks. Do not push unless requested.
- The user-selected audio reference is `input_censored_reviewed.mov`. Reproduce it with `input.reviewed.transcript.json` and `beep_trimmed.wav`; keep these local media files intact.
- Preferred censoring: a single short sound at original speed over part of the word; no looping or stretching. Do not switch to full-sound playback extending the mute beyond the selected word portion without a new user request.
- Keep generated media, source recordings, transcripts, model caches and virtual environments out of Git.
