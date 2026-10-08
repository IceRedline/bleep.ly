#!/usr/bin/env python3
"""Explicit model download; never uploads recordings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from censor.whisperkit_backend import prepare_assets

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / '.cache/whisperkit/model'
prepare_assets(folder, offline=False)
print(folder.resolve())
