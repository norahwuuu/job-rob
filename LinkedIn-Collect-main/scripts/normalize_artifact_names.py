#!/usr/bin/env python3
"""
Normalize legacy artifact filenames under out/ date folders.

Actions:
- _JobList.txt -> job_list.txt
- _EasyApply列表.txt -> easy_apply_list.txt
- _待申请列表.txt -> manual_todo.txt

Default mode is dry-run. Use --apply to perform file copy.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


RENAMES = [
    ("_JobList.txt", "job_list.txt"),
    ("_EasyApply列表.txt", "easy_apply_list.txt"),
    ("_待申请列表.txt", "manual_todo.txt"),
]


def iter_date_dirs(out_dir: Path) -> list[Path]:
    return sorted([p for p in out_dir.iterdir() if p.is_dir() and p.name[:4].isdigit()])


def copy_if_needed(src: Path, dst: Path, apply_changes: bool) -> str:
    if not src.exists():
        return f"skip (missing): {src}"
    if dst.exists():
        return f"skip (exists): {dst}"
    if apply_changes:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return f"copied: {src} -> {dst}"
    return f"plan: {src} -> {dst}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize artifact filenames in out folders")
    parser.add_argument("--out-dir", default="../out", help="Out directory path relative to LinkedIn-Collect-main")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]
    out_dir = (base / args.out_dir).resolve()
    if not out_dir.exists():
        print(f"out dir not found: {out_dir}")
        return

    for day_dir in iter_date_dirs(out_dir):
        print(f"\n[{day_dir.name}]")
        print(copy_if_needed(day_dir / "_JobList.txt", day_dir / "job_list.txt", args.apply))
        print(copy_if_needed(day_dir / "easy_apply" / "_EasyApply列表.txt", day_dir / "easy_apply" / "easy_apply_list.txt", args.apply))
        print(copy_if_needed(day_dir / "manual_apply" / "_待申请列表.txt", day_dir / "manual_apply" / "manual_todo.txt", args.apply))


if __name__ == "__main__":
    main()
