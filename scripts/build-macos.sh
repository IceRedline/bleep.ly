#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CLANG_MODULE_CACHE_PATH="$ROOT/.cache/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$ROOT/.cache/clang"
EXPERIMENT=0
OPEN_APP=0
for ARG in "$@"; do
  case "$ARG" in
    --whisperkit) EXPERIMENT=1 ;;
    --open) OPEN_APP=1 ;;
    *) printf 'Unknown option: %s\n' "$ARG" >&2; exit 2 ;;
  esac
done
if [[ "$EXPERIMENT" == 1 ]]; then
  swift build --disable-sandbox --package-path experiments/WhisperKitRunner --scratch-path .cache/whisperkit-build -c release
fi
swift build --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
APP="$ROOT/build/bleep.ly.app"
if [[ "$EXPERIMENT" == 1 ]]; then APP="$ROOT/build/bleep.ly Lab.app"; fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .cache/swift-build/release/Bleep "$APP/Contents/MacOS/Bleep"
bash scripts/build-icon.sh "$APP/Contents/Resources/AppIcon.icns"
/usr/bin/python3 - "$APP" "$ROOT" "$EXPERIMENT" <<'PY'
import plistlib
import sys
from pathlib import Path
app, root, experiment = sys.argv[1:]
is_lab = experiment == "1"
with (Path(app) / 'Contents/Info.plist').open('wb') as file:
    plistlib.dump({
        'CFBundleExecutable': 'Bleep',
        'CFBundleIdentifier': 'ly.bleep.desktop.lab' if is_lab else 'ly.bleep.desktop',
        'CFBundleName': 'bleep.ly',
        'CFBundleDisplayName': 'bleep.ly Lab' if is_lab else 'bleep.ly',
        'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'AppIcon',
        'CFBundleShortVersionString': '0.3.0' if is_lab else '0.2.0',
        'CFBundleVersion': '4' if is_lab else '3',
        'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True,
        'BleepProjectRoot': root,
        'BleepWhisperKitExperiment': is_lab,
    }, file)
PY
if [[ "$EXPERIMENT" == 1 ]]; then
  mkdir -p "$APP/Contents/Helpers"
  cp .cache/whisperkit-build/release/BleepWhisperKit "$APP/Contents/Helpers/BleepWhisperKit"
  codesign --force --sign - "$APP/Contents/Helpers/BleepWhisperKit"
fi
codesign --force --sign - "$APP"
printf '\nBuilt %s\n' "$APP"
if [[ "$OPEN_APP" == 1 ]]; then open "$APP"; fi
