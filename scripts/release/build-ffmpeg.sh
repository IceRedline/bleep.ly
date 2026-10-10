#!/bin/bash
# Self-contained LGPL FFmpeg: no Homebrew dylibs or third-party codec libraries.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE="$ROOT/.cache/ffmpeg-8.1.2"
ARCHIVE="$ROOT/.cache/ffmpeg-8.1.2.tar.xz"
if [[ ! -f "$ARCHIVE" ]]; then
  curl --fail --location --output "$ARCHIVE.part" https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz
  mv "$ARCHIVE.part" "$ARCHIVE"
fi
xz -t "$ARCHIVE"
echo '464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c  '"$ARCHIVE" | shasum -a 256 -c -
if [[ ! -d "$SOURCE" ]]; then tar -xf "$ARCHIVE" -C "$ROOT/.cache"; fi
cd "$SOURCE"
./configure --prefix="$ROOT/.cache/release-ffmpeg" --disable-autodetect \
  --disable-doc --disable-debug --disable-ffplay --disable-network \
  --enable-audiotoolbox --enable-videotoolbox \
  --extra-cflags=-mmacosx-version-min=14.0 --extra-ldflags=-mmacosx-version-min=14.0
make -j "${BUILD_JOBS:-8}"
make install
