#!/usr/bin/env python3
"""Compatibility entry point for bleeply; prefer python3 bleep.py --help."""
from censor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
