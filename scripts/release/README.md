# macOS release

## TestFlight preparation

The notarized DMG cannot be uploaded directly to TestFlight. Create the macOS app
record for `ly.bleep.desktop` in App Store Connect. In Xcode's account settings,
create **Apple Distribution** and **Mac Installer Distribution** certificates.
Create and download a **Mac App Store Connect** provisioning profile for the
explicit Bundle ID and the distribution certificate. Keep profiles and keys out
of Git. An app-specific password or App Store Connect API credentials are also
needed by the chosen upload tool; do not place them in source or shell history.

Build and test the Swift app, then commit the source before preparing a candidate:

```sh
bash scripts/release/build-pyav.sh
python3 scripts/release/app_store_runtime.py fetch
python3 scripts/release/testflight-macos.py prepare \
  --output build/testflight-0.1.9-22 --build-number 22 \
  --copyright 'Copyright © 2026 YOUR NAME'
```

This clones the existing release and replaces its Swift executable with
`.cache/swift-build/release/Bleep`. Python engine source and word lists come from
the same committed checkout. The pinned runtimes remain from the source
release except PyAV, which is replaced in both by the locally built LGPL wheel,
and SciPy, which uses the hash-pinned OpenBLAS wheel. The unused Tcl/Tk GUI stack
is removed. The compiler runtime source archive, including LGPL libquadmath,
and its rebuild instructions accompany the SciPy wheel. See
[the native dependency audit](../../docs/app-store-binary-audit.md) for details.
Offline policy/support documents and the corresponding FFmpeg/PyAV sources are
included. `preparation.json` records the origins and wheel checksum. Source DMGs and apps are
never modified. The resulting candidate is unsigned until the next step. Use a
new, monotonically increasing build number for every upload.

```sh
security find-identity -v -p codesigning
python3 scripts/release/testflight-macos.py sign \
  --app build/testflight-0.1.9-22/bleeply.app \
  --profile /path/to/bleeply-store.provisionprofile \
  --identity APPLICATION_CERTIFICATE_SHA1 \
  --installer-identity '3rd Party Mac Developer Installer: YOUR NAME (TEAM_ID)' \
  --pkg build/testflight-0.1.9-22/bleeply-0.1.9-22.pkg
```

The build number above is an example; increase it after every upload.
Signing also rejects the four known API references from the build 21 review
and verifies the compiler runtime source archive and license notices.
Signing checks the profile's app, platform, expiration and certificate before
changing the candidate. Child executables inherit App Sandbox; Python retains
its JIT entitlements. The parent grants network access for model downloads and
access to user-selected files, plus persistent bookmarks. Packaging verifies
signatures and every installer BOM entry’s read/traverse permissions locally; it does **not** mean Apple has accepted the build. Validate
and upload the PKG with Transporter or Apple's command-line tools, then wait for
processing in App Store Connect before assigning it to a TestFlight group.

Before distribution, test file selection, drag and drop, restored reviews, custom
sounds, downloads, preview and export from the signed sandboxed app. Its container
has separate preferences and model caches from the DMG build. The release smoke
script must run as a child of a sandboxed host when checking inherited helper
entitlements; executing a helper with `com.apple.security.inherit` directly from
a normal shell is not a valid sandbox test. Local runtime probes cover library
imports, Metal/MPS, JIT and transcript-driven exports, but do not replace Apple
validation or a TestFlight installation test.

## Direct-download release

Release **0.1.9** supports **Apple Silicon, macOS 15.0 or later**. MLX stays at
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
Python 3.11 environments at `.venv` and `.runtime/asr-env`, then install the matching
lockfile. The latter includes a pinned GigaAM source revision.

```sh
uv python install 3.11.15 --install-dir .cache/release-python --cache-dir .cache/uv
uv venv .cache/dmg-tools --python .cache/release-python/cpython-3.11.15-macos-aarch64-none/bin/python3.11
uv pip install --python .cache/dmg-tools/bin/python dmgbuild==1.6.7 pillow==12.3.0
```

Install a **Developer ID Application** identity in the login keychain. Create a
notarytool profile interactively; never put a password in source or shell history:

```sh
xcrun notarytool store-credentials bleeply-notary --apple-id YOUR_APPLE_ID --team-id YOUR_TEAM_ID
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
bash scripts/release/build-pyav.sh
python3 scripts/release/bundle-macos.py --version 0.1.9 --build-number 22
python3 scripts/release/sign-macos.py --identity 'Developer ID Application: YOUR NAME (TEAM_ID)' build/release/bleeply.app
python3 scripts/release/smoke-test.py build/release/bleeply.app
```

The FFmpeg script builds unmodified LGPL sources with only system frameworks,
without Homebrew dynamic libraries, network protocols, GPL or nonfree options.
The source archive SHA-256 is pinned. Include that archive with every binary
release. Do not silently substitute a system FFmpeg.

Both distribution channels use the same OpenBLAS-backed SciPy wheel and omit
the optional Tcl/Tk stack. Run `python3 scripts/release/app_store_runtime.py fetch`
before bundling either channel. Version and build numbers must match for a paired
release. Sandbox entitlements, provisioning and signing identities differ by
channel. For an existing checked Store candidate, create the matching direct
download payload with `paired-release.py prepare`, sign it with Developer ID,
then run `paired-release.py verify` against both signed apps before publishing.
The verifier compares all resources and normalizes Mach-O signatures before
comparing executable code; only channel-specific metadata is allowed to differ.

PyAV 18.1.0's upstream wheel vendors its own FFmpeg and x264/x265 libraries,
independently of our command-line helpers. Never ship it unchanged. The separate
`build-pyav.sh` builds unmodified FFmpeg 8.1.2 shared libraries with GPL, nonfree,
version-3 components and external codec autodetection disabled, then compiles
PyAV and makes the wheel relocatable with delocate. The build runs in an ASCII
temporary path because pkg-config escapes non-ASCII checkout paths incorrectly.
Both packaging paths install this wheel and preserve its BSD license and authors.
The exact source archives, LGPL license, configurations and rebuild instructions
are embedded under `ThirdParty/Sources`. `pyav_distribution.audit` rejects
x264/x265 files, unsafe configure flags, unknown builds and mismatched sources;
TestFlight signing runs it again before creating a package. The wheel supports
macOS 14+, while the app's other dependencies still require macOS 15+.

The smoke check runs with an isolated HOME and a PATH containing only bundled
tools and macOS system utilities. It checks imports in both Python runtimes,
Metal, PyTorch MPS, Numba JIT, transcript import, mute timing, WAV export and
byte-identical video packet copying. Optional real offline recognition:

```sh
python3 scripts/release/smoke-test.py build/release/bleeply.app \
  --recognize /path/to/short-russian-recording.mov --model-cache "$PWD/.cache"
```

Run the same smoke check on a copy in a different directory and from the mounted
final read-only DMG. A model cache supplied here is test input, never bundled.

## Notarize and package

Sign every nested Mach-O with hardened runtime and a secure timestamp, then the
outer app. Python executables allow JIT and unsigned executable memory for Numba;
library validation stays enabled. Use the same Developer ID for all code.

```sh
.cache/dmg-tools/bin/python scripts/release/build-dmg.py --version 0.1.9
codesign --sign 'Developer ID Application: YOUR NAME (TEAM_ID)' --timestamp dist/bleeply-0.1.9-arm64.dmg
xcrun notarytool submit dist/bleeply-0.1.9-arm64.dmg --keychain-profile bleeply-notary --wait
xcrun stapler staple dist/bleeply-0.1.9-arm64.dmg
xcrun stapler validate dist/bleeply-0.1.9-arm64.dmg
spctl --assess --type open --context context:primary-signature --verbose=2 dist/bleeply-0.1.9-arm64.dmg
```

Apple's [distribution workflow](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)
notarizes the outermost container: submitting the signed DMG also produces tickets
for the signed app and its nested code. Staple the distribution DMG directly.
The image uses Apple's recommended UDZO format. If S3 Transfer Acceleration is
slow on the current network, pass `--no-s3-acceleration` to `notarytool submit`.

Never rebuild or alter a signed/notarized app after submission. Generate SHA256SUMS
only after the final DMG is stapled. Review the notarization log, verify the
mounted image and Finder layout, then publish the matching tag and release.
The installer uses a 720 × 560 window with extra vertical space for Finder chrome.
Check that both footer lines remain visible with Finder's path and status bars
shown: Finder can restore those global preferences despite the DMG settings.

Payload directories and executables use mode `0755`; other regular files use
`0644`. Normalize before signing, never after notarization. The bundler, signers,
PKG verifier, and mounted DMG verifier reject files inaccessible to non-root users.
This prevents temporary Python wheel overlays from introducing `0700` directories.
