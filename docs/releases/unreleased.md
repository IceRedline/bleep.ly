# Unreleased

## Storage limits

- Temporary preview audio is limited to 4 GiB per session and eight recent variants. Older disposable audio is removed first, preserving the current playback and the audio needed for an update.
- Recognition cache and history share a 256 MiB budget with a 30-day retention period. Cleanup runs before and after analysis; reused transcripts refresh their retention date.
- Abandoned preview and processing folders are cleaned up after a crash. Active app instances and workers retain their temporary files.
- Previews that cannot fit the budget or leave 1 GiB of free disk space show an actionable message. Original playback and export remain available.
- Models, original recordings, exported files, custom sounds, and the saved review are preserved. Settings explains the storage policy.

## Model downloads

- New installations ask for permission when the selected recognition model is missing, without requiring a visit to Settings.
- **OK** allows downloads of missing models, remembers the choice, and continues processing the same file automatically.
- **No** cancels processing without downloading. Users can enable downloads later in Settings.
- Already downloaded models work offline without a prompt. Existing download permission is preserved.
- Missing-model errors explain how to enable downloads instead of displaying Python cache diagnostics. Recordings remain on the Mac.
