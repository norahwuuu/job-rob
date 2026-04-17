#!/usr/bin/env python3
"""
Backward-compatible entrypoint.
Use optimize_artifacts_layout.py instead.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    target = Path(__file__).with_name("optimize_artifacts_layout.py")
    runpy.run_path(str(target), run_name="__main__")
