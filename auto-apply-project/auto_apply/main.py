from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_profile
from .engine import AutoApplyEngine
from .linkedin_source import (
    extract_easy_apply_candidates,
    load_applied_job_ids,
    load_jobs_progress,
    parse_easy_todo,
)
from .models import Job
from .store import JsonStore


def load_jobs(path: Path) -> list[Job]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Job.from_dict(item) for item in payload]


def cmd_run(args: argparse.Namespace) -> None:
    jobs = load_jobs(Path(args.jobs))
    engine = AutoApplyEngine(load_profile(), Path(args.data_dir))
    summary = engine.run(jobs)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.data_dir))
    report = store.load_json(store.results_path, {"summary": {}, "events": []})
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_run_easy(args: argparse.Namespace) -> None:
    items = load_jobs_progress(Path(args.jobs_progress))
    jobs = extract_easy_apply_candidates(items)
    # 先筛选真正可投递岗位，再应用 --max，避免被 discovered 条目占位。
    jobs = [
        job for job in jobs
        if job.source_status == "resume_ready" and bool(job.resume_path)
    ]
    if args.max is not None:
        jobs = jobs[: args.max]

    use_ai_fill: bool | None = False if getattr(args, "no_ai", False) else None
    engine = AutoApplyEngine(load_profile(use_ai_fill=use_ai_fill), Path(args.data_dir))
    result = engine.run_easy_apply_only(jobs)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def cmd_run_easy_todo(args: argparse.Namespace) -> None:
    jobs = parse_easy_todo(Path(args.easy_todo))
    if args.job_id:
        target_id = str(args.job_id).strip()
        jobs = [job for job in jobs if str(job.job_id) == target_id]
    if args.jobs_progress:
        applied_ids = load_applied_job_ids(Path(args.jobs_progress))
        jobs = [job for job in jobs if str(job.job_id) not in applied_ids]
    if args.max is not None:
        jobs = jobs[: args.max]
    use_ai_fill: bool | None = False if getattr(args, "no_ai", False) else None
    engine = AutoApplyEngine(load_profile(use_ai_fill=use_ai_fill), Path(args.data_dir))
    result = engine.run_easy_apply_only(jobs)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto apply scaffold")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory for progress and result JSON files",
    )
    sub = parser.add_subparsers(required=True)

    run_parser = sub.add_parser("run", help="Run apply pipeline")
    run_parser.add_argument("--jobs", required=True, help="Path to jobs JSON input")
    run_parser.set_defaults(func=cmd_run)

    report_parser = sub.add_parser("report", help="Show latest run report")
    report_parser.set_defaults(func=cmd_report)

    easy_parser = sub.add_parser("run-easy", help="Run Easy Apply only flow")
    easy_parser.add_argument(
        "--jobs-progress",
        required=True,
        help="Path to LinkedIn jobs_progress.json",
    )
    easy_parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Optional cap for number of jobs to process",
    )
    easy_parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Disable LLM merge; use resume scan + env + todo only",
    )
    easy_parser.set_defaults(func=cmd_run_easy)

    easy_todo_parser = sub.add_parser("run-easy-todo", help="Run Easy Apply by easy_todo.txt")
    easy_todo_parser.add_argument(
        "--easy-todo",
        required=True,
        help="Path to easy_todo.txt",
    )
    easy_todo_parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Optional cap for number of jobs to process",
    )
    easy_todo_parser.add_argument(
        "--jobs-progress",
        required=False,
        default=None,
        help="Optional jobs_progress.json for idempotent applied filtering",
    )
    easy_todo_parser.add_argument(
        "--job-id",
        required=False,
        default=None,
        help="Optional single job_id for targeted apply retry",
    )
    easy_todo_parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Disable LLM merge; use resume scan + env + todo only",
    )
    easy_todo_parser.set_defaults(func=cmd_run_easy_todo)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
