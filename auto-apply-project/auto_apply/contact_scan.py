from __future__ import annotations

import re
from typing import Any


_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
)
# Loose international phone capture (resume lines often include +CC ...)
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,6}",
)


def scan_resume_contacts(text: str) -> dict[str, Any]:
    """Extract obvious email/phone tokens from raw resume text."""
    emails = _EMAIL_RE.findall(text or "")
    phones = []
    for m in _PHONE_RE.finditer(text or ""):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 8:
            phones.append(raw)
    email = emails[0] if emails else ""
    phone = phones[0] if phones else ""
    return {"email": email, "phone": phone, "emails_found": emails[:3], "phones_found": phones[:3]}
