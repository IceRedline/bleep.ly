#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:?Usage: build-theme.sh /path/to/bleep.ly.app}"
# AppKit resolves the global accent from the main bundle, not a SwiftPM bundle.
xcrun actool "$ROOT/macOS/Resources/Theme.xcassets" \
  --compile "$APP/Contents/Resources" --platform macosx \
  --minimum-deployment-target 14.0 --accent-color AccentColor
/usr/bin/python3 - "$APP/Contents/Info.plist" <<'PY'
import plistlib
import sys
from pathlib import Path
path = Path(sys.argv[1])
info = plistlib.loads(path.read_bytes())
info['NSAccentColorName'] = 'AccentColor'
path.write_bytes(plistlib.dumps(info))
PY
