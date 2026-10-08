#!/bin/bash
# Convert the supplied source image into all sizes required by a macOS app icon.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/icon.PNG"
OUTPUT="${1:?Supply output .icns path}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/bleep-icon.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
for SIZE in 16 32 128 256 512; do
  sips -s format png -z "$SIZE" "$SIZE" "$SOURCE" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
  RETINA=$((SIZE * 2))
  sips -s format png -z "$RETINA" "$RETINA" "$SOURCE" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$OUTPUT"
