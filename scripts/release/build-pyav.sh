#!/bin/bash
# Build PyAV against our own LGPL-only shared FFmpeg, never the PyPI binary wheel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUTPUT="$ROOT/.cache/pyav-lgpl"
# pkg-config escapes non-ASCII paths byte by byte; PyAV cannot decode them.
# Keep compiler/pkg-config paths ASCII even when the checkout path is not.
WORK="$(mktemp -d /private/tmp/bleep-pyav.XXXXXX)"
mkdir -p "$WORK/sources" "$WORK/wheels"
fetch() {
  local url="$1" destination="$2" digest="$3"
  if [[ ! -f "$destination" ]]; then
    curl --fail --location "$url" -o "$destination.part"
    mv "$destination.part" "$destination"
  fi
  echo "$digest  $destination" | shasum -a 256 -c -
}
FFMPEG="$WORK/sources/ffmpeg-8.1.2.tar.xz"
if [[ -d "$OUTPUT/sources" ]]; then cp "$OUTPUT/sources/"*.tar.* "$WORK/sources/"; fi
# Reuse the exact source archive already distributed with the direct release.
if [[ ! -f "$FFMPEG" && -f "$ROOT/dist/0.1.7/ffmpeg-8.1.2.tar.xz" ]]; then
  cp "$ROOT/dist/0.1.7/ffmpeg-8.1.2.tar.xz" "$FFMPEG"
fi
fetch https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz "$FFMPEG" \
  464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c
fetch https://files.pythonhosted.org/packages/8d/f4/f22114d30d3435e38c6af2b4870f37b864403dca6ae7af747a289ce0a18e/av-18.1.0.tar.gz \
  "$WORK/sources/av-18.1.0.tar.gz" 47bfc286e1bc9de7ab4681fc2b575cd2460a66919d31ffe1bd5aa54fae531a28
if [[ ! -d "$WORK/ffmpeg-8.1.2" ]]; then tar -xf "$FFMPEG" -C "$WORK"; fi
mkdir -p "$WORK/ffmpeg-build"
cd "$WORK/ffmpeg-build"
"$WORK/ffmpeg-8.1.2/configure" --prefix="$WORK/ffmpeg" \
  --enable-shared --disable-static --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 \
  --disable-programs --disable-doc --disable-debug --disable-network \
  --enable-audiotoolbox --enable-videotoolbox \
  --extra-cflags=-mmacosx-version-min=14.0 --extra-ldflags=-mmacosx-version-min=14.0
make -j "${BUILD_JOBS:-8}"
make install
cd "$ROOT"
if [[ ! -x "$WORK/venv/bin/python" ]]; then .venv/bin/python -m venv "$WORK/venv"; fi
"$WORK/venv/bin/python" -m pip install 'pip==26.0.1' 'setuptools==82.0.0' 'wheel==0.46.3' 'cython==3.2.4' 'delocate==0.13.0'
export PKG_CONFIG_LIBDIR="$WORK/ffmpeg/lib/pkgconfig"
export PKG_CONFIG_PATH="$PKG_CONFIG_LIBDIR"
export MACOSX_DEPLOYMENT_TARGET=14.0
"$WORK/venv/bin/python" -m pip wheel --no-build-isolation --no-deps \
  "$WORK/sources/av-18.1.0.tar.gz" --wheel-dir "$WORK/raw-wheels"
"$WORK/venv/bin/delocate-wheel" --require-archs arm64 --check-archs \
  --wheel-dir "$WORK/wheels" "$WORK"/raw-wheels/av-18.1.0-*.whl
cp "$WORK/ffmpeg-build/config.h" "$WORK/sources/FFmpeg-config.h"
cp "$WORK/ffmpeg-build/ffbuild/config.mak" "$WORK/sources/FFmpeg-config.mak"
cp "$0" "$WORK/sources/build-pyav.sh"
cp "$ROOT/scripts/release/build-ffmpeg.sh" "$WORK/sources/build-ffmpeg.sh"
cp "$WORK/ffmpeg-8.1.2/COPYING.LGPLv2.1" "$WORK/sources/FFmpeg-LGPL-2.1.txt"
mkdir -p "$OUTPUT/wheels" "$OUTPUT/sources"
cp "$WORK/wheels/"*.whl "$OUTPUT/wheels/"
cp "$WORK/sources/"* "$OUTPUT/sources/"
printf '\nBuilt LGPL PyAV wheel in %s\nBuild directory: %s\n' "$OUTPUT/wheels" "$WORK"
