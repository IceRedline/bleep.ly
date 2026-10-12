# Unreleased

- Increase the temporary preview audio budget from 4 GiB to 7 GiB per session, allowing a 77-minute recording to prepare its first preview and update it while the previous preview remains playable. Older variants are still evicted automatically, and the 1 GiB free-disk reserve remains in place.

- Store the development GPU Python environment in `.runtime/asr-env` instead of `.cache/asr-env`, so clearing disposable caches cannot remove recognition dependencies. Packaged apps continue to use their embedded runtimes.
