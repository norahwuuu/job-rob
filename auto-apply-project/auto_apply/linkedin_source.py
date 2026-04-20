from __future__ import annotations

import json
from pathlib import Path
import re

from .models import Job


def load_jobs_progress(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_applied_job_ids(path: Path) -> set[str]:
    items = load_jobs_progress(path)
    applied_ids: set[str] = set()
    for row in items:
        status = str(row.get("status", "")).strip().lower()
        if status == "applied":
            applied_ids.add(str(row.get("job_id", "")).strip())
    return applied_ids


def map_progress_item_to_job(item: dict) -> Job:
    return Job(
        job_id=str(item.get("job_id", "")),
        title=item.get("title", ""),
        company=item.get("company", ""),
        url=item.get("url", ""),
        easy_apply=bool(item.get("is_easy_apply", False)),
        is_easy_apply=bool(item.get("is_easy_apply", False)),
        score=int(float(item.get("ai_score", 0) or 0)),
        source_status=str(item.get("status", "")),
        resume_path=str(item.get("resume_path", "")),
        job_description=str(item.get("job_description", "") or ""),
        location=str(item.get("location", "") or ""),
    )


def extract_easy_apply_candidates(items: list[dict]) -> list[Job]:
    jobs: list[Job] = []
    for item in items:
        if not bool(item.get("is_easy_apply", False)):
            continue
        job = map_progress_item_to_job(item)
        jobs.append(job)
    return jobs


def detect_base_country(text: str) -> str:
    lower = (text or "").lower()
    if any(
        token in lower
        for token in [
            "switzerland",
            "schweiz",
            "zurich",
            "zuerich",
            "zürich",
            "geneva",
            "basel",
            "olten",
            "bern",
            "lausanne",
            "lugano",
            "winterthur",
        ]
    ):
        return "switzerland"
    if any(token in lower for token in ["germany", "deutschland", "berlin", "munich", "muenchen", "hamburg", "frankfurt", "essen"]):
        return "germany"
    return "germany"


def contact_by_country(base_country: str) -> tuple[str, str]:
    if base_country == "switzerland":
        return "+41 799067274", "Unterfuehrungsstrasse 25 4600 Olten"
    return "+49 176 6087 6657", "alfredstr. 56, essen,germany"


def parse_easy_todo(path: Path) -> list[Job]:
    lines = path.read_text(encoding="utf-8").splitlines()
    jobs: list[Job] = []

    current_title = ""
    current_company = ""
    current_url = ""
    current_pdf = ""
    current_base_country = ""
    current_status = ""

    title_pattern = re.compile(r"^\d+\.\s+(.*?)\s+@\s+(.*?)$")
    url_prefix = "Job Link:"
    pdf_prefix = "PDF Path:"
    base_prefix = "Base Country:"
    status_prefix = "Status:"

    for raw_line in lines:
        line = raw_line.strip()
        title_match = title_pattern.match(line)
        if title_match:
            if current_url and current_pdf:
                base_country = (current_base_country or detect_base_country(f"{current_title} {current_company}")).lower()
                phone, address = contact_by_country(base_country)
                jobs.append(
                    Job(
                        job_id=current_url.rstrip("/").split("/")[-1],
                        title=current_title,
                        company=current_company,
                        url=current_url,
                        easy_apply=True,
                        is_easy_apply=True,
                        source_status=(current_status or "resume_ready"),
                        resume_path=current_pdf,
                        base_country=base_country,
                        contact_phone=phone,
                        contact_address=address,
                    )
                )
            current_title = title_match.group(1).strip()
            current_company = title_match.group(2).strip()
            current_url = ""
            current_pdf = ""
            current_base_country = ""
            current_status = ""
            continue

        if line.startswith(url_prefix):
            current_url = line[len(url_prefix):].strip()
            continue
        if line.startswith(pdf_prefix):
            current_pdf = line[len(pdf_prefix):].strip()
            continue
        if line.startswith(base_prefix):
            current_base_country = line[len(base_prefix):].strip().lower()
            continue
        if line.startswith(status_prefix):
            current_status = line[len(status_prefix):].strip().lower()
            continue

    if current_url and current_pdf:
        base_country = (current_base_country or detect_base_country(f"{current_title} {current_company}")).lower()
        phone, address = contact_by_country(base_country)
        jobs.append(
            Job(
                job_id=current_url.rstrip("/").split("/")[-1],
                title=current_title,
                company=current_company,
                url=current_url,
                easy_apply=True,
                is_easy_apply=True,
                source_status=(current_status or "resume_ready"),
                resume_path=current_pdf,
                base_country=base_country,
                contact_phone=phone,
                contact_address=address,
            )
        )

    return jobs
