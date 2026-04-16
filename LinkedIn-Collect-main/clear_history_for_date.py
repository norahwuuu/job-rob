#!/usr/bin/env python3
"""按日历日清除 out/ 中与该日相关的爬取状态（默认：本机当天）。

- jobs_history.json: 移除 seen_key_dates 为当日的键；移除 jobs[] 中 added_date 为当日的项；
- jobs_progress.json: 移除 title|||company 落在上述待删键集合中的岗位；
- crawl_progress.json: updated_at 日期为当日时，将 last_page 置 0；
- jobs_list_cache.json: 删除 _scraped_at 日期为当日的条目（若存在）。

旧数据仅有 seen_keys、无 seen_key_dates 时，除 jobs[].added_date 与 crawl 进度外，
无法按日精确删掉历史里更早写入的键；自本脚本与 linkedin_scraper 更新后，新爬取的
岗位会写入 seen_key_dates，即可按日清理。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from typing import Any


def _out_path() -> str:
    # 与 linkedin_scraper._out_dir 一致：相对当前工作目录
    base = os.environ.get("PIPELINE__OUTPUT__BASE_DIR", "./out")
    return os.path.abspath(base)


def _make_key(title: str, company: str) -> str:
    return f"{(title or '').lower().strip()}|||{(company or '').lower().strip()}"


def _load_json(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="要清除的日期（默认：本机当天）",
    )
    args = p.parse_args()
    target = args.date or date.today().isoformat()

    out = _out_path()
    history_path = os.path.join(out, "jobs_history.json")
    progress_path = os.path.join(out, "jobs_progress.json")
    crawl_path = os.path.join(out, "crawl_progress.json")
    list_cache_path = os.path.join(out, "jobs_list_cache.json")

    removed_keys: set[str] = set()

    history = _load_json(history_path)
    if isinstance(history, dict):
        seen_keys = set(history.get("seen_keys") or [])
        seen_key_dates = history.get("seen_key_dates") or {}
        if not isinstance(seen_key_dates, dict):
            seen_key_dates = {}

        for key, d in list(seen_key_dates.items()):
            if d == target:
                removed_keys.add(key)

        jobs = history.get("jobs") or []
        if isinstance(jobs, list):
            kept_jobs = []
            for job in jobs:
                if not isinstance(job, dict):
                    kept_jobs.append(job)
                    continue
                if job.get("added_date") == target:
                    k = _make_key(job.get("title", ""), job.get("company", ""))
                    if k != "|||":
                        removed_keys.add(k)
                    continue
                kept_jobs.append(job)
            history["jobs"] = kept_jobs

        history["seen_keys"] = sorted(seen_keys - removed_keys)
        for k in removed_keys:
            seen_key_dates.pop(k, None)
        history["seen_key_dates"] = seen_key_dates
        history["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_json(history_path, history)
        print(
            f"jobs_history.json: 移除 {len(removed_keys)} 个当日键 "
            f"(seen_key_dates + added_date)，剩余 seen_keys={len(history['seen_keys'])}"
        )
    else:
        print("jobs_history.json: 跳过（文件不存在或格式不是对象）")

    progress = _load_json(progress_path)
    scraped_ids_path = os.path.join(out, "jobs_scraped_ids.json")
    if isinstance(progress, list) and removed_keys:
        before = len(progress)
        drop_ids = {
            str(j.get("job_id"))
            for j in progress
            if isinstance(j, dict)
            and j.get("job_id")
            and _make_key(j.get("title", ""), j.get("company", "")) in removed_keys
        }
        progress = [
            j
            for j in progress
            if not isinstance(j, dict)
            or _make_key(j.get("title", ""), j.get("company", "")) not in removed_keys
        ]
        _save_json(progress_path, progress)
        print(f"jobs_progress.json: {before} -> {len(progress)}（按移除键过滤）")
        scraped = _load_json(scraped_ids_path)
        if isinstance(scraped, list) and drop_ids:
            before_s = len(scraped)
            scraped = [x for x in scraped if str(x) not in drop_ids]
            if len(scraped) != before_s:
                _save_json(scraped_ids_path, scraped)
            print(f"jobs_scraped_ids.json: {before_s} -> {len(scraped)}（若存在）")
    elif isinstance(progress, list):
        print("jobs_progress.json: 无待删键，未改写")

    crawl = _load_json(crawl_path)
    if isinstance(crawl, dict):
        n = 0
        for _slot, entry in list(crawl.items()):
            if not isinstance(entry, dict):
                continue
            at = (entry.get("updated_at") or "")[:10]
            if at == target:
                entry["last_page"] = 0
                n += 1
        if n:
            _save_json(crawl_path, crawl)
        print(f"crawl_progress.json: 将 {n} 个当日 updated_at 条件的 last_page 重置为 0")

    cache = _load_json(list_cache_path)
    if isinstance(cache, list):
        before = len(cache)
        cache = [
            j
            for j in cache
            if not isinstance(j, dict)
            or (j.get("_scraped_at") or "")[:10] != target
        ]
        if len(cache) != before:
            _save_json(list_cache_path, cache)
        print(f"jobs_list_cache.json: {before} -> {len(cache)}")
    elif cache is not None:
        print("jobs_list_cache.json: 跳过（非列表）")
    else:
        print("jobs_list_cache.json: 不存在，跳过")


if __name__ == "__main__":
    main()
