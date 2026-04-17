from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class JobState(str, Enum):
    NEW = "NEW"
    ELIGIBLE = "ELIGIBLE"
    SKIPPED = "SKIPPED"
    OPENED = "OPENED"
    REVIEW = "REVIEW"
    SUBMITTED = "SUBMITTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_MANUAL = "FAILED_MANUAL"


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    url: str
    easy_apply: bool = True
    location: str = ""
    requires_visa: bool = False
    score: int = 0
    state: JobState = JobState.NEW
    reason: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    source_status: str = ""
    is_easy_apply: bool = True
    resume_path: str = ""
    base_country: str = ""
    contact_phone: str = ""
    contact_address: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.__dict__.copy()
        payload["state"] = self.state.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        payload = data.copy()
        payload["state"] = JobState(payload.get("state", JobState.NEW.value))
        return cls(**payload)


@dataclass
class Event:
    job_id: str
    from_state: str
    to_state: str
    reason: str
    at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class EasyApplyResult:
    auto_applied: list[dict[str, Any]]
    manual_todo: list[dict[str, Any]]
    skipped: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_applied": self.auto_applied,
            "manual_todo": self.manual_todo,
            "skipped": self.skipped,
        }
