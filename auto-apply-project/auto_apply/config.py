from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional


@dataclass
class CandidateProfile:
    has_work_visa: bool = False
    min_score: int = 60
    daily_limit: int = 20
    use_ai_resume_fill: bool = True
    ai_model: str = "gpt-4o-mini"


def load_profile(*, use_ai_fill: Optional[bool] = None) -> CandidateProfile:
    env_ai = os.getenv("APPLY_USE_AI_FILL", "true").lower() == "true"
    effective_ai = env_ai if use_ai_fill is None else bool(use_ai_fill)
    model = (
        os.getenv("APPLY_AI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "gpt-4o-mini"
    ).strip()
    return CandidateProfile(
        has_work_visa=os.getenv("APPLY_HAS_WORK_VISA", "false").lower() == "true",
        min_score=int(os.getenv("APPLY_MIN_SCORE", "60")),
        daily_limit=int(os.getenv("APPLY_DAILY_LIMIT", "20")),
        use_ai_resume_fill=effective_ai,
        ai_model=model,
    )
