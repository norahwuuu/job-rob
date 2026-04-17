#!/usr/bin/env python3
"""
Backward-compatible entrypoint.
Use normalize_artifact_filenames.py instead.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    target = Path(__file__).with_name("normalize_artifact_filenames.py")
    runpy.run_path(str(target), run_name="__main__")
