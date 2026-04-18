#!/usr/bin/env python3
"""
Optimize artifacts/ naming layout without breaking runtime compatibility.

What it does:
1) Copy legacy list filenames to canonical names under each date's easy_apply/ and manual_apply/.
2) Move legacy `_JobList.txt` (if present) to legacy_names/; after canonical copies exist, move legacy easy_apply/manual_apply list files to legacy_names/.
3) Renames accidental nested artifacts/artifacts folder to artifacts/_legacy_nested_artifacts.

Default is dry-run. Use --apply to execute changes.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DATE_DIR_GLOB = "20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]"


def is_date_dir(path: Path) -> bool:
    return path.is_dir() and path.name[:4].isdigit() and len(path.name) == 10


def log(op: str, src: Path, dst: Path | None = None) -> None:
    if dst is None:
        print(f"{op}: {src}")
    else:
        print(f"{op}: {src} -> {dst}")


def ensure_copy(src: Path, dst: Path, apply: bool) -> None:
    if not src.exists() or dst.exists():
        return
    log("copy", src, dst)
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def move_if_exists(src: Path, dst: Path, apply: bool) -> None:
    if not src.exists():
        return
    log("move", src, dst)
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def optimize_date_dir(day_dir: Path, apply: bool) -> None:
    # Canonical files in subdirs
    ensure_copy(day_dir / "easy_apply" / "_EasyApply列表.txt", day_dir / "easy_apply" / "easy_apply_list.txt", apply)
    ensure_copy(day_dir / "manual_apply" / "_待申请列表.txt", day_dir / "manual_apply" / "manual_todo.txt", apply)

    # Move legacy names into legacy_names folder (after canonical copy exists)
    legacy_dir = day_dir / "legacy_names"
    move_if_exists(day_dir / "_JobList.txt", legacy_dir / "_JobList.txt", apply)
    if (day_dir / "easy_apply" / "easy_apply_list.txt").exists():
        move_if_exists(day_dir / "easy_apply" / "_EasyApply列表.txt", legacy_dir / "_EasyApply列表.txt", apply)
    if (day_dir / "manual_apply" / "manual_todo.txt").exists():
        move_if_exists(day_dir / "manual_apply" / "_待申请列表.txt", legacy_dir / "_待申请列表.txt", apply)


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize artifacts folder naming")
    parser.add_argument("--out-dir", default="../artifacts", help="artifacts directory path relative to pipeline-orchestrator")
    parser.add_argument("--apply", action="store_true", help="apply changes (default dry-run)")
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]
    out_dir = (base / args.out_dir).resolve()
    if not out_dir.exists():
        print(f"not found: {out_dir}")
        return

    print(f"artifacts_dir={out_dir}")
    print(f"mode={'apply' if args.apply else 'dry-run'}")

    # Handle accidental nested artifacts/artifacts
    nested = out_dir / "artifacts"
    if nested.exists() and nested.is_dir():
        move_if_exists(nested, out_dir / "_legacy_nested_artifacts", args.apply)

    for path in sorted(out_dir.iterdir()):
        if is_date_dir(path):
            print(f"\n[{path.name}]")
            optimize_date_dir(path, args.apply)


if __name__ == "__main__":
    main()
