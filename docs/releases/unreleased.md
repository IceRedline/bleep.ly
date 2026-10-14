# Unreleased

- Show real byte progress for GigaAM, Parakeet, Qwen ASR and Qwen ForcedAligner downloads, including downloaded/total MB and a remaining-time estimate based on measured transfer speed. Keep stage timers stable as byte counters change, exclude resumed bytes from speed estimates, and stop counting down when progress stalls.
- Replace the generic experimental-model preparation label with named checking, downloading and loading stages. Display an animated indeterminate bar immediately while the download size is unknown or models are loading into memory. Download percentages are measured, and reaching the end of a transfer does not claim completion before the downloader returns successfully.
- Fix a model-preparation error in the desktop worker (`TextIOWrapper is not JSON serializable`) by sharing one JSON event emitter between direct calls and app launches. Add cold-start worker coverage to the packaged-app smoke check.
