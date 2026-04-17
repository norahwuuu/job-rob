#!/usr/bin/env python3
"""
不重爬、不重评 LLM，仅根据现有 JD 与 pipeline 配置重跑 JobFilter，
修正 jobs_progress.json 中的 passed_filter / ai_reason（及 experience_years、is_english）。

适用：爬取阶段曾把 passed_filter 默认写成 false，但 ai_reason 仍为 [AI初筛]… 等错位数据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    # .../pipeline-orchestrator/scripts/this.py -> job-bot
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _norm_status(s: Any) -> str:
    v = (str(s or "").strip().lower())
    aliases = {
        "pending": "discovered",
        "resume_generated": "resume_ready",
    }
    return aliases.get(v, v)


# 与 run_pipeline 终态一致：不覆盖用户已推进的流程
_SKIP_STATUS = frozenset(
    {
        "applied",
        "closed",
        "failed",
        "skipped",
        "resume_ready",
    }
)


def _dict_to_job_listing(d: Dict[str, Any]):
    import linkedin_scraper

    ey = d.get("experience_years")
    if ey is not None:
        try:
            ey = int(ey)
        except (TypeError, ValueError):
            ey = None
    return linkedin_scraper.JobListing(
        job_id=str(d.get("job_id", "") or ""),
        title=str(d.get("title", "") or ""),
        company=str(d.get("company", "") or ""),
        location=str(d.get("location", "") or ""),
        url=str(d.get("url", "") or ""),
        is_easy_apply=bool(d.get("is_easy_apply", False)),
        job_description=str(d.get("job_description", "") or ""),
        experience_required=d.get("experience_required"),
        posted_time=d.get("posted_time"),
        applicants=d.get("applicants"),
        external_apply_url=d.get("external_apply_url"),
        is_english=bool(d.get("is_english", True)),
        experience_years=ey,
        passed_filter=bool(d.get("passed_filter", False)),
        ai_score=float(d.get("ai_score", 0) or 0),
        ai_reason=str(d.get("ai_reason", "") or ""),
        priority_tier=int(d.get("priority_tier", 99) or 99),
        priority_label=str(d.get("priority_label", "") or ""),
    )


def repair(
    jobs_path: Path,
    config_path: Path,
    dry_run: bool,
    only_misaligned: bool,
) -> None:
    orch = config_path.parent
    sys.path.insert(0, str(orch))
    import linkedin_scraper  # noqa: E402

    cfg = _load_yaml(config_path)
    flt = cfg.get("filter") or {}
    max_y = int(flt.get("max_experience_years", 10) or 10)
    min_y = int(flt.get("min_experience_years", 0) or 0)
    reject_german_jd = bool(flt.get("exclude_german", True))

    job_filter = linkedin_scraper.JobFilter(
        max_experience_years=max_y,
        min_experience_years=min_y,
        reject_german_jd=reject_german_jd,
    )

    raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("jobs JSON 应为数组")

    jobs: List[Dict[str, Any]] = raw
    changed = 0
    examined = 0
    skipped_terminal = 0

    for d in jobs:
        st = _norm_status(d.get("status"))
        if st in _SKIP_STATUS:
            skipped_terminal += 1
            continue

        examined += 1
        old_pf = bool(d.get("passed_filter", False))
        old_reason = str(d.get("ai_reason", "") or "")

        jl = _dict_to_job_listing(d)
        jl = job_filter.filter_job(jl)
        new_pf = bool(jl.passed_filter)

        misaligned = (not old_pf) and ("[AI初筛]" in old_reason or "[AI预过滤]" in old_reason)
        if only_misaligned and not misaligned and old_pf == new_pf:
            continue

        updates: Dict[str, Any] = {
            "passed_filter": new_pf,
            "experience_years": jl.experience_years,
            "is_english": jl.is_english,
        }
        if not new_pf:
            updates["ai_reason"] = jl.ai_reason
        # 通过规则过滤时保留原有 ai_reason / ai_score（多为 LLM 评分），除非先前是明显错位
        elif misaligned:
            if old_reason.strip().startswith("[AI初筛]"):
                rest = old_reason.replace("[AI初筛]", "", 1).strip()
                updates["ai_reason"] = (
                    f"[规则筛查通过] 初筛说明：{rest}" if rest else "[规则筛查通过]"
                )
            else:
                updates["ai_reason"] = old_reason

        need_write = any(d.get(k) != v for k, v in updates.items())
        if need_write:
            d.update(updates)
            changed += 1

    print(
        f"检查 {examined} 条（跳过终态 {skipped_terminal} 条）；"
        f"写入更新 {changed} 条；only_misaligned={only_misaligned} dry_run={dry_run}"
    )

    if dry_run:
        return

    jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存: {jobs_path}")


def main() -> None:
    root = _repo_root()
    p = argparse.ArgumentParser(description="重跑 JobFilter 修正 jobs_progress 中 passed_filter / ai_reason")
    p.add_argument(
        "--jobs",
        type=Path,
        default=root / "artifacts" / "jobs_progress.json",
        help="jobs_progress.json 路径",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=root / "pipeline-orchestrator" / "pipeline_config.yaml",
        help="pipeline_config.yaml（读取 filter 段）",
    )
    p.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    p.add_argument(
        "--only-misaligned",
        action="store_true",
        help="仅处理「passed_filter=false 且 ai_reason 含 [AI初筛]/[AI预过滤]」的错位行",
    )
    args = p.parse_args()

    if not args.jobs.exists():
        raise SystemExit(f"找不到文件: {args.jobs}")
    if not args.config.exists():
        raise SystemExit(f"找不到配置: {args.config}")

    repair(args.jobs.resolve(), args.config.resolve(), args.dry_run, args.only_misaligned)


if __name__ == "__main__":
    main()
