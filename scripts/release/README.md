# macOS release

Release **0.1.1** supports **Apple Silicon, macOS 15.0 or later**. MLX stays at
0.32.3, but uses the official Sequoia wheels pinned by URL and SHA-256 in
`requirements-mlx-macos15.lock`. A version-only pip pin on a Tahoe build host
selects different wheels requiring macOS 26.2, which caused the 0.1.0 restriction.
The bundler overlays the compatible wheels in both embedded runtimes without
changing developer environments. `bundle-macos.py` inspects every Mach-O and
fails for missing deployment metadata or a target newer than macOS 15.0.

CI installs both complete release lockfiles on macOS 15, audits their binaries,
and checks backend imports and MLX CPU execution. Hosted VMs lack a Metal GPU;
local release smoke tests additionally exercise Metal, MPS and real inference.

The app contains two relocatable CPython 3.11.15 runtimes, the Python engine,
word lists, FFmpeg/FFprobe 8.1.2, and the WhisperKit helper. Separate core and GPU
runtimes preserve the tested Hugging Face and PyTorch versions. Package license
files remain inside their `*.dist-info` directories. No recordings, transcripts,
model weights, developer settings or signing keys belong in the app or Git.

## Prerequisites

Use an Apple Silicon Mac with Xcode, uv, and the two project Python environments.
Their installed dependencies must match `requirements-core.lock` and
`requirements-gpu.lock`; the bundler refuses a mismatch. To recreate them, create
Python 3.11 environments at `.venv` and `.cache/asr-env`, then install the matching
lockfile. The latter includes a pinned GigaAM source revision.

```sh
uv python install 3.11.15 --install-dir .cache/release-python --cache-dir .cache/uv
uv venv .cache/dmg-tools --python .cache/release-python/cpython-3.11.15-macos-aarch64-none/bin/python3.11
uv pip install --python .cache/dmg-tools/bin/python dmgbuild==1.6.7 pillow==12.3.0
```

Install a **Developer ID Application** identity in the login keychain. Create a
notarytool profile interactively; never put a password in source or shell history:

```sh
xcrun notarytool store-credentials bleep-ly-notary --apple-id YOUR_APPLE_ID --team-id YOUR_TEAM_ID
```

## Build and check

Commit source changes before bundling so `runtime.json` identifies the source.
Run Python and Swift tests as documented in the project README, then:
Preserve the previous signed app before rebuilding (for example, rename
`build/release` to `build/release-0.1.0`). The bundler and DMG builder refuse to
overwrite existing release artifacts.

```sh
bash scripts/build-macos.sh
bash scripts/release/build-ffmpeg.sh
python3 scripts/release/bundle-macos.py --version 0.1.1
python3 scripts/release/sign-macos.py --identity 'Developer ID Application: YOUR NAME (TEAM_ID)' build/release/bleep.ly.app
python3 scripts/release/smoke-test.py build/release/bleep.ly.app
```

The FFmpeg script builds unmodified LGPL sources with only system frameworks,
without Homebrew dynamic libraries, network protocols, GPL or nonfree options.
The source archive SHA-256 is pinned. Include that archive with every binary
release. Do not silently substitute a system FFmpeg.

The smoke check runs with an isolated HOME and a PATH containing only bundled
tools and macOS system utilities. It checks imports in both Python runtimes,
Metal, PyTorch MPS, Numba JIT, transcript import, mute timing, WAV export and
byte-identical video packet copying. Optional real offline recognition:

```sh
python3 scripts/release/smoke-test.py build/release/bleep.ly.app \
  --recognize /path/to/short-russian-recording.mov --model-cache "$PWD/.cache"
```

Run the same smoke check on a copy in a different directory and from the mounted
final read-only DMG. A model cache supplied here is test input, never bundled.

## Notarize and package

Sign every nested Mach-O with hardened runtime and a secure timestamp, then the
outer app. Python executables allow JIT and unsigned executable memory for Numba;
library validation stays enabled. Use the same Developer ID for all code.

```sh
.cache/dmg-tools/bin/python scripts/release/build-dmg.py --version 0.1.1
codesign --sign 'Developer ID Application: YOUR NAME (TEAM_ID)' --timestamp dist/bleep.ly-0.1.1-arm64.dmg
xcrun notarytool submit dist/bleep.ly-0.1.1-arm64.dmg --keychain-profile bleep-ly-notary --wait
xcrun stapler staple dist/bleep.ly-0.1.1-arm64.dmg
xcrun stapler validate dist/bleep.ly-0.1.1-arm64.dmg
spctl --assess --type open --context context:primary-signature --verbose=2 dist/bleep.ly-0.1.1-arm64.dmg
```

Apple's [distribution workflow](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)
notarizes the outermost container: submitting the signed DMG also produces tickets
for the signed app and its nested code. Staple the distribution DMG directly.
The image uses Apple's recommended UDZO format. If S3 Transfer Acceleration is
slow on the current network, pass `--no-s3-acceleration` to `notarytool submit`.

Never rebuild or alter a signed/notarized app after submission. Generate SHA256SUMS
only after the final DMG is stapled. Review the notarization log, verify the
mounted image and Finder layout, then publish the matching tag and release.
