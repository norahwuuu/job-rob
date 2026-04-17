from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import CandidateProfile
from .models import EasyApplyResult, Event, Job, JobState, utc_now_iso
from .store import JsonStore


@dataclass
class RunSummary:
    total: int = 0
    submitted: int = 0
    skipped: int = 0
    failed_manual: int = 0
    failed_retryable: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


class AutoApplyEngine:
    def __init__(self, profile: CandidateProfile, data_dir: Path) -> None:
        self.profile = profile
        self.store = JsonStore(data_dir)
        self.events: list[Event] = []

    def run(self, jobs: Iterable[Job]) -> RunSummary:
        summary = RunSummary()
        daily_submitted = 0
        progress: list[dict] = []

        for job in jobs:
            summary.total += 1

            if daily_submitted >= self.profile.daily_limit:
                self.transition(job, JobState.SKIPPED, "Reached daily limit")
                summary.skipped += 1
                progress.append(job.to_dict())
                continue

            if job.score < self.profile.min_score:
                self.transition(job, JobState.SKIPPED, "Score below threshold")
                summary.skipped += 1
                progress.append(job.to_dict())
                continue

            if job.requires_visa and not self.profile.has_work_visa:
                self.transition(job, JobState.SKIPPED, "No matching visa")
                summary.skipped += 1
                progress.append(job.to_dict())
                continue

            self.transition(job, JobState.ELIGIBLE, "Policy passed")

            try:
                self.simulate_open_job(job)
                self.simulate_fill_form(job)
                self.simulate_submit(job)
                daily_submitted += 1
                summary.submitted += 1
            except ValueError as err:
                self.transition(job, JobState.FAILED_MANUAL, str(err))
                summary.failed_manual += 1
            except RuntimeError as err:
                self.transition(job, JobState.FAILED_RETRYABLE, str(err))
                summary.failed_retryable += 1

            progress.append(job.to_dict())

        self.store.save_json(self.store.progress_path, progress)
        self.store.save_json(
            self.store.results_path,
            {
                "summary": summary.to_dict(),
                "events": [item.to_dict() for item in self.events],
                "updated_at": utc_now_iso(),
            },
        )
        return summary

    def run_easy_apply_only(self, jobs: Iterable[Job]) -> EasyApplyResult:
        auto_applied: list[dict] = []
        manual_todo: list[dict] = []
        skipped: list[dict] = []
        progress: list[dict] = []

        for job in jobs:
            if not job.is_easy_apply:
                self.transition(job, JobState.SKIPPED, "Not an Easy Apply job")
                skipped.append(self._result_entry(job))
                progress.append(job.to_dict())
                continue

            if job.source_status != "resume_ready":
                self.transition(job, JobState.SKIPPED, "Status is not resume_ready")
                skipped.append(self._result_entry(job))
                progress.append(job.to_dict())
                continue

            if not job.resume_path:
                self.transition(job, JobState.FAILED_MANUAL, "Missing resume_path")
                manual_todo.append(self._result_entry(job))
                progress.append(job.to_dict())
                continue

            try:
                self.simulate_open_job(job)
                self.simulate_fill_form(job)
                self.simulate_submit(job)
                auto_applied.append(self._result_entry(job))
            except ValueError as err:
                self.transition(job, JobState.FAILED_MANUAL, str(err))
                manual_todo.append(self._result_entry(job))
            except RuntimeError as err:
                self.transition(job, JobState.FAILED_RETRYABLE, str(err))
                manual_todo.append(self._result_entry(job))

            progress.append(job.to_dict())

        result = EasyApplyResult(
            auto_applied=auto_applied,
            manual_todo=manual_todo,
            skipped=skipped,
        )
        # Do not overwrite LinkedIn main jobs_progress.json format here.
        # Keep apply outputs in dedicated files only.
        self.store.save_json(self.store.results_path, result.to_dict())
        self.store.save_json(self.store.root / "auto_applied.json", auto_applied)
        self.store.save_json(self.store.root / "manual_todo.json", manual_todo)
        return result

    def transition(self, job: Job, to_state: JobState, reason: str) -> None:
        from_state = job.state.value
        job.state = to_state
        job.reason = reason
        job.updated_at = utc_now_iso()
        self.events.append(
            Event(
                job_id=job.job_id,
                from_state=from_state,
                to_state=to_state.value,
                reason=reason,
            )
        )

    def simulate_open_job(self, job: Job) -> None:
        self.transition(job, JobState.OPENED, "Job page opened")

    def simulate_fill_form(self, job: Job) -> None:
        if not job.easy_apply:
            raise ValueError("External apply flow requires manual action")
        phone = job.contact_phone or "+49 176 6087 6657"
        address = job.contact_address or "alfredstr. 56, essen,germany"
        base_country = job.base_country or "germany"
        self.transition(
            job,
            JobState.REVIEW,
            f"Form completed with base={base_country}, phone={phone}, address={address}",
        )

    def simulate_submit(self, job: Job) -> None:
        self.transition(job, JobState.SUBMITTED, "Application submitted")

    def _result_entry(self, job: Job) -> dict:
        return {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "state": job.state.value,
            "reason": job.reason,
            "resume_path": job.resume_path,
            "source_status": job.source_status,
            "base_country": job.base_country,
            "contact_phone": job.contact_phone,
            "contact_address": job.contact_address,
        }
