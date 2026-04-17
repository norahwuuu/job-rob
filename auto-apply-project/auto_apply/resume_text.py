from __future__ import annotations

from pathlib import Path


def read_resume_plaintext(resume_path: Path) -> str:
    """Return best-effort plain text from PDF or UTF-8 text file."""
    suffix = resume_path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(resume_path)
    if suffix in (".txt", ".md"):
        return resume_path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported resume format: {suffix} (supported: .pdf, .txt, .md)")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as err:
        raise ImportError("Install pypdf to read PDF resumes: pip install pypdf") from err

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
    return "\n".join(parts).strip()
