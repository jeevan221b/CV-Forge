"""Human-readable match report (Markdown) for download."""
from __future__ import annotations

from typing import Any, Optional

from ..models import STATUS_LABELS, JDAnalysis, MatchReport, Suggestion

_IMPORTANCE = {"must": "Must have", "important": "Important", "nice": "Nice to have"}
_ORDER = ["supported", "needs_confirmation", "indirect", "unsupported", "unclear"]


def render_match_report(*, resume_name: str, resume_version: int, created_at: str, analysis: Optional[JDAnalysis],
                        report: Optional[MatchReport], suggestions: list[Suggestion],
                        validation: Optional[dict[str, Any]]) -> str:
    title = (analysis.job_title if analysis else "") or "Untitled role"
    lines = [f"# Match report — {title}", ""]
    if analysis and analysis.employer:
        lines.append(f"- Employer: {analysis.employer}")
    lines += [f"- Master resume: {resume_name} (version {resume_version})", f"- Session created: {created_at}", ""]

    if report and analysis:
        s = report.score
        lines += ["## Estimated overlap", "", f"**{s.value}%** — {s.label}", "", s.explanation, ""]
        lines += ["| Status | Requirements |", "|---|---|"]
        lines += [f"| {STATUS_LABELS[k]} | {s.counts.get(k, 0)} |" for k in _ORDER]
        lines.append("")
        reqs = {r.id: r for r in analysis.requirements}
        for status in _ORDER:
            group = [m for m in report.matches if m.status == status and m.requirement_id in reqs]
            if not group:
                continue
            lines += [f"## {STATUS_LABELS[status]}", ""]
            for m in group:
                r = reqs[m.requirement_id]
                lines.append(f"### {r.text}")
                lines.append(f"- {_IMPORTANCE[r.importance]} · {r.category.replace('_', ' ')}")
                if r.keywords:
                    lines.append(f"- Terms checked: {', '.join(r.keywords)}")
                if m.missing_terms:
                    lines.append(f"- Not documented: {', '.join(m.missing_terms)}")
                if m.note:
                    lines.append(f"- Note: {m.note}")
                for ev in m.evidence:
                    lines.append(f"- Evidence ({ev.strength}, {ev.context}): “{ev.excerpt}”")
                lines.append("")
    else:
        lines += ["No job description has been analysed for this session.", ""]

    decided = [s for s in suggestions if s.status in ("accepted", "modified")]
    if decided:
        lines += ["## Approved changes", ""]
        for s in decided:
            lines += [f"### {s.target_label}", f"- Original: {s.original_text or '(empty)'}",
                      f"- Approved: {s.applied_text}", f"- Source: {'edited by you' if s.status == 'modified' else 'AI suggestion'}"]
            if s.requires_confirmation:
                lines.append("- You confirmed these flagged points: " + "; ".join(f.message for f in s.flags if f.severity != "info"))
            lines.append("")
    rejected = sum(1 for s in suggestions if s.status == "rejected")
    invalid = sum(1 for s in suggestions if s.status == "invalid")
    if suggestions:
        lines += [f"Suggestions: {len(decided)} approved, {rejected} rejected, "
                  f"{sum(1 for s in suggestions if s.status == 'pending')} pending, {invalid} rejected by validation.", ""]

    if validation and validation.get("formatting"):
        fmt = validation["formatting"]
        lines += ["## Document checks", "", f"PDF pages: {fmt.get('pages', 0)} · engine: {fmt.get('engine') or 'n/a'}", ""]
        lines += ["| Result | Category | Check | Detail |", "|---|---|---|---|"]
        for c in fmt.get("checks", []):
            detail = c["detail"] + (" — " + "; ".join(c["items"][:6]) if c["items"] else "")
            lines.append(f"| {c['status'].upper()} | {c['category']} | {c['label']} | {detail.replace('|', '/')} |")
        lines += ["", fmt.get("disclaimer", ""), ""]
    return "\n".join(lines).rstrip() + "\n"
