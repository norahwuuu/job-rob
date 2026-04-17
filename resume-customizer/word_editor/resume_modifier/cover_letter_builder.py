"""Plain-text cover letter fallback when AI cover generation fails (see AIAnalyzer.generate_cover_letter_english)."""

from __future__ import annotations


def render_cover_letter(
    company_name: str,
    job_title: str,
    *,
    applicant_full_name: str = "",
) -> str:
    """
    Build a short English cover letter including work-authorization and mobility context.

    Content reflects: residence in CH/DE, German Chancenkarte as a national Category D visa,
    no Swiss work permit, open to relocation and remote.
    """
    company = (company_name or "your company").strip() or "your company"
    title = (job_title or "the advertised role").strip() or "the advertised role"
    name = (applicant_full_name or "").strip()

    closing = f"Sincerely,\n{name}\n" if name else "Sincerely,\n"

    return f"""Dear Hiring Manager,

I am writing to express my strong interest in the {title} position at {company}.

I currently split my time between Switzerland and Germany. I hold Germany's Opportunity Card (Chancenkarte), which is a national Category D visa and authorizes employment in Germany; I am available to start on short notice. I do not currently hold a Swiss work permit. I am open to relocation for the right opportunity and am fully open to remote work as well as hybrid arrangements.

I would welcome the opportunity to discuss how my experience can contribute to your team.

{closing}""".rstrip() + "\n"
