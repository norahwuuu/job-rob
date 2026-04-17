from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class CandidateProfile:
    has_work_visa: bool = False
    min_score: int = 60
    daily_limit: int = 20


def load_profile() -> CandidateProfile:
    return CandidateProfile(
        has_work_visa=os.getenv("APPLY_HAS_WORK_VISA", "false").lower() == "true",
        min_score=int(os.getenv("APPLY_MIN_SCORE", "60")),
        daily_limit=int(os.getenv("APPLY_DAILY_LIMIT", "20")),
    )
