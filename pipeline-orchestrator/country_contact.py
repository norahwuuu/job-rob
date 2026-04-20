from __future__ import annotations

from typing import Iterable

_SWISS_TOKENS = (
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
)

_GERMANY_TOKENS = (
    "germany",
    "deutschland",
    "berlin",
    "munich",
    "muenchen",
    "hamburg",
    "frankfurt",
    "essen",
)


def detect_base_country_from_text(parts: Iterable[str]) -> str:
    text = " ".join(str(x or "") for x in parts).lower()
    if any(token in text for token in _SWISS_TOKENS):
        return "switzerland"
    if any(token in text for token in _GERMANY_TOKENS):
        return "germany"
    return "germany"


def contact_by_country(base_country: str) -> tuple[str, str]:
    if str(base_country or "").strip().lower() == "switzerland":
        return "+41 799067274", "Unterfuehrungsstrasse 25 4600 Olten"
    return "+49 176 6087 6657", "alfredstr. 56, essen,germany"
