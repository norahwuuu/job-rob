"""
生成后的简历校验：重复章节标题、要点格式（前导语加粗）等启发式检查。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from .resume_doc_checks import iter_all_paragraphs, normalize_section_title, paragraph_needs_leading_bold_fix
from .resume_parser import ResumeParser, ParsedResume


def _duplicate_section_titles(parsed: ParsedResume) -> List[str]:
    raw = [s.title.strip() for s in parsed.sections if (s.title or "").strip()]
    if len(raw) < 2:
        return []

    by_norm: Counter[str] = Counter(normalize_section_title(t) for t in raw)
    dup_keys = {k for k, c in by_norm.items() if c > 1}
    if not dup_keys:
        return []

    seen: set[str] = set()
    out: List[str] = []
    for t in raw:
        key = normalize_section_title(t)
        if key in dup_keys and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _format_issue_messages_from_doc(doc: Any, max_issues: int = 12) -> List[str]:
    """基于 Word 段落与 runs 检查要点格式。"""
    issues: List[str] = []

    def scan(p: Any) -> None:
        if len(issues) >= max_issues:
            return
        t = p.text.strip()
        if not t or ":" not in t:
            return
        if paragraph_needs_leading_bold_fix(p):
            preview = t[:100] + ("…" if len(t) > 100 else "")
            issues.append(
                f'Bullet may be missing bold leading phrase before colon: "{preview}"'
            )

    for para in iter_all_paragraphs(doc):
        scan(para)
    return issues


def validate_resume_docx(doc_path: str) -> Dict[str, Any]:
    """解析 .docx 并做启发式校验（不阻断流水线）。"""
    parser = ResumeParser(doc_path)
    parsed = parser.parse()

    dups = _duplicate_section_titles(parsed)
    fmt = _format_issue_messages_from_doc(parser.doc)
    warnings: List[str] = []
    if dups:
        warnings.append(
            "Duplicate section title(s) detected: "
            + "; ".join(repr(t) for t in dups)
        )
    if fmt:
        warnings.extend(fmt)

    return {
        "ok": len(dups) == 0 and len(fmt) == 0,
        "duplicate_section_titles": dups,
        "format_issue_hints": fmt,
        "warnings": warnings,
        "section_count": len(parsed.sections),
    }
