#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
.venv/bin/python -m venv .runtime/asr-env
.runtime/asr-env/bin/python -m pip install --cache-dir .cache/pip -r requirements-experimental-gpu.txt
