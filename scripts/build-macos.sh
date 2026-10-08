#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CLANG_MODULE_CACHE_PATH="$ROOT/.cache/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$ROOT/.cache/clang"
swift build --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
APP="$ROOT/build/bleep.ly.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .cache/swift-build/release/Bleep "$APP/Contents/MacOS/Bleep"
/usr/bin/python3 - "$APP" "$ROOT" <<'PY'
import plistlib
import sys
from pathlib import Path
app, root = sys.argv[1:]
with (Path(app) / 'Contents/Info.plist').open('wb') as file:
    plistlib.dump({
        'CFBundleExecutable': 'Bleep',
        'CFBundleIdentifier': 'ly.bleep.desktop',
        'CFBundleName': 'bleep.ly',
        'CFBundleDisplayName': 'bleep.ly',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '0.2.0',
        'CFBundleVersion': '3',
        'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True,
        'BleepProjectRoot': root,
    }, file)
PY
codesign --force --sign - "$APP"
printf '\nBuilt %s\n' "$APP"
if [[ "${1:-}" == "--open" ]]; then open "$APP"; fi
