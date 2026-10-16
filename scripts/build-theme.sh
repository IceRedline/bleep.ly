#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:?Usage: build-theme.sh /path/to/bleeply.app}"
# One catalog must contain the theme AND the primary icon. Compiling a second
# catalog into this directory would replace Assets.car and lose its AppIcon.
/usr/bin/python3 "$ROOT/scripts/release/app_icons.py" build "$APP"
