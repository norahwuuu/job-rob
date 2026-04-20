from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .contact_scan import scan_resume_contacts
from .linkedin_source import contact_by_country
from .models import Job
from .resume_text import read_resume_plaintext

_MAX_RESUME_CHARS = 14_000
_MAX_JD_CHARS = 4_000

_ANSWER_SCHEMA_HINT = """{
  "full_name": "string or null",
  "email": "string or null",
  "phone": "string or null",
  "city": "string or null",
  "country": "string or null",
  "postal_code": "string or null",
  "full_address_line": "string or null",
  "linkedin_url": "string or null",
  "work_authorization": "short phrase, e.g. EU citizen / Swiss B permit / need sponsorship — only if inferable",
  "requires_sponsorship": "yes|no|unknown",
  "notice_period": "short phrase e.g. 4 weeks / immediately / unknown",
  "years_of_professional_experience": "number or null if unknown",
  "extra_screening_answers": [
    {"question": "typical LinkedIn screening question", "answer": "concise truthful answer"}
  ],
  "field_source": { "email": "resume|env|todo|inferred", "...": "..." }
}"""


def resolve_resume_path(job: Job, data_dir: Path) -> Path | None:
    raw = (job.resume_path or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_file():
        return p
    cwd = Path.cwd()
    for base in (cwd, data_dir, data_dir.parent, cwd.parent):
        cand = (base / raw).resolve()
        if cand.is_file():
            return cand
    return None


def _env_personal() -> dict[str, str]:
    return {
        "full_name": os.getenv("PERSONAL_FULL_NAME", "").strip(),
        "first_name": os.getenv("PERSONAL_FIRST_NAME", "").strip(),
        "email": os.getenv("PERSONAL_EMAIL", "").strip(),
        "phone": os.getenv("PERSONAL_PHONE_NUMBER", "").strip(),
    }


def _merge_layer(
    *,
    ai: dict[str, Any],
    scanned: dict[str, Any],
    envp: dict[str, str],
    job: Job,
) -> dict[str, Any]:
    """Prefer resume, then per-job todo hints, then env, then AI for remaining keys."""
    out: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def set_field(key: str, value: Any, source: str) -> None:
        if value is None or value == "":
            return
        if out.get(key) in (None, "", []):
            out[key] = value
            sources[key] = source

    def force_field(key: str, value: Any, source: str) -> None:
        """Always set (used when job base country mandates a contact bundle)."""
        if value is None or value == "":
            return
        out[key] = value
        sources[key] = source

    set_field("email", scanned.get("email"), "resume")

    bc_norm = (job.base_country or "").strip().lower()
    # 公司 base 在瑞士时：电话/地址用瑞士（todo 或默认），不用简历里德国号码盖住 todo。
    if bc_norm == "switzerland":
        phone_sw, addr_sw = contact_by_country("switzerland")
        force_field("phone", (job.contact_phone or phone_sw).strip(), "todo")
        force_field("full_address_line", (job.contact_address or addr_sw).strip(), "todo")
        force_field("country", "Switzerland", "todo")
    else:
        set_field("phone", scanned.get("phone"), "resume")
        set_field("phone", (job.contact_phone or "").strip(), "todo")
        addr = (job.contact_address or "").strip()
        if addr:
            set_field("full_address_line", addr, "todo")
            if not out.get("country"):
                bc = (job.base_country or "").strip()
                if bc:
                    set_field("country", bc.title(), "todo")

    set_field("email", envp.get("email"), "env")
    set_field("phone", envp.get("phone"), "env")
    set_field("full_name", envp.get("full_name"), "env")

    # AI fills gaps (and may refine wording)
    for key in (
        "full_name",
        "email",
        "phone",
        "city",
        "country",
        "postal_code",
        "full_address_line",
        "linkedin_url",
        "work_authorization",
        "requires_sponsorship",
        "notice_period",
        "years_of_professional_experience",
    ):
        if key not in ai or ai.get(key) in (None, "", []):
            continue
        if key in out and out[key] not in (None, "", []):
            continue
        out[key] = ai[key]
        sources[key] = "inferred"

    fs_ai = ai.get("field_source") if isinstance(ai.get("field_source"), dict) else {}
    for k, v in fs_ai.items():
        if k not in sources and isinstance(v, str):
            sources[k] = v

    extras = ai.get("extra_screening_answers")
    if isinstance(extras, list):
        out["extra_screening_answers"] = [
            {"question": str(x.get("question", "")).strip(), "answer": str(x.get("answer", "")).strip()}
            for x in extras
            if isinstance(x, dict) and x.get("question") and x.get("answer")
        ][:8]
    else:
        out["extra_screening_answers"] = []

    out["field_source"] = sources
    return out


def _openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        return None
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    kwargs: dict[str, str] = {"api_key": key}
    base = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
    if base:
        kwargs["base_url"] = base
    return OpenAI(**kwargs)


def _call_ai_fill(
    *,
    model: str,
    resume_excerpt: str,
    job: Job,
) -> dict[str, Any]:
    client = _openai_client()
    if not client:
        return {}

    jd = (job.job_description or "")[:_MAX_JD_CHARS]
    user = (
        f"Job title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location hint: {job.location or job.base_country}\n\n"
        f"Job description excerpt:\n{jd}\n\n"
        f"Resume text:\n{resume_excerpt}\n"
    )
    system = (
        "You fill LinkedIn Easy Apply screening fields as JSON only, no markdown.\n"
        "Rules:\n"
        "- Use ONLY the resume for factual claims (employers, dates, degrees, certifications).\n"
        "- For contact/location: prefer values explicitly present in the resume.\n"
        "- If a value is not in the resume, you may infer conservatively from context "
        "(e.g. country from phone prefix, languages in JD vs resume) and mark field_source as inferred.\n"
        "- Never invent employers, degrees, or credentials.\n"
        "- Keep extra_screening_answers to at most 5 common questions employers ask "
        "(e.g. work authorization, notice period, years of experience, willingness to relocate) "
        "that you can answer from resume + reasonable inference.\n"
        "- If unsure, use null or 'unknown'.\n"
        f"Output shape:\n{_ANSWER_SCHEMA_HINT}\n"
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    content = (resp.choices[0].message.content or "").strip()
    return json.loads(content) if content else {}


def _coerce_years(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        m = re.search(r"(\d+)", val)
        if m:
            return int(m.group(1))
    return None


def build_easy_apply_answers(
    job: Job,
    *,
    data_dir: Path,
    use_ai: bool,
    ai_model: str,
) -> tuple[dict[str, Any], list[str]]:
    """
    Build a JSON-friendly bundle of answers for LinkedIn Easy Apply common fields.

    Returns (answers_dict, log_notes).
    """
    notes: list[str] = []
    path = resolve_resume_path(job, data_dir)
    if not path:
        raise ValueError(f"Resume file not found: {job.resume_path!r}")

    resume_full = read_resume_plaintext(path)
    if not resume_full.strip():
        raise ValueError(f"No text extracted from resume: {path}")

    excerpt = resume_full[:_MAX_RESUME_CHARS]
    scanned = scan_resume_contacts(resume_full)
    envp = _env_personal()

    ai_payload: dict[str, Any] = {}
    if use_ai:
        try:
            ai_payload = _call_ai_fill(model=ai_model, resume_excerpt=excerpt, job=job)
            if ai_payload:
                notes.append("ai_fill:ok")
            else:
                notes.append("ai_fill:skipped_no_client")
        except Exception as err:
            notes.append(f"ai_fill:error:{err.__class__.__name__}")
            ai_payload = {}

    merged = _merge_layer(ai=ai_payload, scanned=scanned, envp=envp, job=job)
    years = _coerce_years(merged.get("years_of_professional_experience"))
    if years is not None:
        merged["years_of_professional_experience"] = years

    merged["resume_path"] = str(path)
    merged["resume_chars"] = len(resume_full)
    return merged, notes
