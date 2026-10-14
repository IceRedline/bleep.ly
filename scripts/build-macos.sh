#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CLANG_MODULE_CACHE_PATH="$ROOT/.cache/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$ROOT/.cache/clang"
OPEN_APP=0
for ARG in "$@"; do
  case "$ARG" in
    --whisperkit) printf "WhisperKit is included in bleep.ly; --whisperkit is no longer needed.\n" ;;
    --open) OPEN_APP=1 ;;
    *) printf 'Unknown option: %s\n' "$ARG" >&2; exit 2 ;;
  esac
done
swift build --disable-sandbox --package-path experiments/WhisperKitRunner --scratch-path .cache/whisperkit-build -c release
swift build --disable-sandbox --package-path macOS --scratch-path .cache/swift-build -c release
APP="$ROOT/build/bleep.ly.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .cache/swift-build/release/Bleep "$APP/Contents/MacOS/Bleep"
mkdir -p "$APP/Contents/Resources/Documentation"
cp docs/privacy-policy.md docs/support.md docs/third-party.md "$APP/Contents/Resources/Documentation/"
bash scripts/build-icon.sh "$APP/Contents/Resources/AppIcon.icns"
/usr/bin/python3 - "$APP" "$ROOT" <<'PY'
import plistlib
import sys
import uuid
from pathlib import Path
app, root = sys.argv[1:]
with (Path(app) / 'Contents/Info.plist').open('wb') as file:
    plistlib.dump({
        'CFBundleExecutable': 'Bleep',
        'CFBundleIdentifier': 'ly.bleep.desktop',
        'CFBundleName': 'bleep.ly',
        'CFBundleDisplayName': 'bleep.ly',
        'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'AppIcon',
        'CFBundleShortVersionString': '0.1.7',
        'CFBundleVersion': '16',
        'BleepBuildID': str(uuid.uuid4()),
        'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True,
        'BleepProjectRoot': root,
    }, file)
PY
bash scripts/build-theme.sh "$APP"
mkdir -p "$APP/Contents/Helpers"
cp .cache/whisperkit-build/release/BleepWhisperKit "$APP/Contents/Helpers/BleepWhisperKit"
codesign --force --sign - "$APP/Contents/Helpers/BleepWhisperKit"
codesign --force --sign - "$APP"
# Remove only the generated legacy bundle after the replacement is successfully signed.
# Its preferences, drafts and saved sounds remain available for migration.
/usr/bin/python3 - "$ROOT/build/bleep.ly Lab.app" <<'PYTHON'
import plistlib
import shutil
import sys
from pathlib import Path
legacy = Path(sys.argv[1])
info = legacy / 'Contents/Info.plist'
if info.is_file() and not legacy.is_symlink():
    with info.open('rb') as file:
        if plistlib.load(file).get('CFBundleIdentifier') == 'ly.bleep.desktop.lab':
            shutil.rmtree(legacy)
PYTHON
printf '\nBuilt %s\n' "$APP"
if [[ "$OPEN_APP" == 1 ]]; then open "$APP"; fi
