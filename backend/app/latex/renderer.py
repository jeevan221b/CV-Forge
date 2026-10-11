"""Resume data -> ordered plain-text view -> escaped template context -> LaTeX source.

The same `ResumeView` feeds both the template and the PDF validator, so the validator checks
the PDF against exactly what was meant to be printed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..lexicon import canonical_term
from ..models import ResumeConfig, ResumeProfile
from .escape import escape_latex, escape_url, normalise_url

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "ats_resume.tex.j2"
HEADINGS = {"summary": "Summary", "skills": "Skills", "experience": "Experience", "projects": "Projects",
            "education": "Education", "certifications": "Certifications"}


@dataclass
class ViewEntry:
    heading: str
    dates: str = ""
    subheading: str = ""
    link: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class ViewSection:
    key: str  # summary | skills | experience | projects | education | certifications | other
    kind: str  # summary | skills | entries | list
    heading: str
    text: str = ""
    groups: list[tuple[str, list[str]]] = field(default_factory=list)
    entries: list[ViewEntry] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


@dataclass
class ResumeView:
    name: str
    contact_items: list[str]
    email: str
    links: list[str]
    sections: list[ViewSection]

    def all_text(self) -> list[str]:
        """Every string that is supposed to be printed."""
        out = [self.name, *self.contact_items, *(display_url(u) for u in self.links)]
        for s in self.sections:
            out.append(s.heading)
            if s.text:
                out.append(s.text)
            for category, items in s.groups:
                out.extend([category, *items])
            for e in s.entries:
                out.extend([e.heading, e.dates, e.subheading, display_url(e.link) if e.link else "", *e.bullets])
            out.extend(s.lines)
        return [t for t in out if t]


def display_url(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?|^mailto:", "", url.strip()).rstrip("/")


def _join(*parts: str, sep: str = ", ") -> str:
    return sep.join(p.strip() for p in parts if p and p.strip())


def _prioritise(items: list[str], priority: list[str]) -> list[str]:
    rank = {canonical_term(p).lower(): i for i, p in enumerate(priority)}
    return sorted(items, key=lambda it: rank.get(canonical_term(it).lower(), len(rank)))  # stable


def build_view(profile: ResumeProfile, config: ResumeConfig) -> ResumeView:
    """Apply section order, optional sections and skill priority. Pure reordering/filtering:
    this function never rewrites content."""
    c = profile.contact
    sections: list[ViewSection] = []
    for key in config.section_order:
        if key == "summary" and config.include_summary and profile.summary.strip():
            sections.append(ViewSection(key, "summary", HEADINGS[key], text=profile.summary.strip()))
        elif key == "skills" and profile.skills:
            groups = [(g.category.strip(), _prioritise([i.strip() for i in g.items if i.strip()],
                                                       config.prioritized_skills))
                      for g in profile.skills if any(i.strip() for i in g.items)]
            if groups:
                sections.append(ViewSection(key, "skills", HEADINGS[key], groups=groups))
        elif key == "experience" and profile.experience:
            entries = [ViewEntry(heading=e.title.strip() or e.employer.strip(), dates=e.dates.strip(),
                                 subheading=_join(e.employer if e.title.strip() else "", e.location),
                                 bullets=[b.text.strip() for b in e.bullets if b.text.strip()])
                       for e in profile.experience]
            sections.append(ViewSection(key, "entries", HEADINGS[key], entries=entries))
        elif key == "projects" and config.include_projects and profile.projects:
            entries = [ViewEntry(heading=p.name.strip(), dates=p.dates.strip(), subheading=p.tech.strip(),
                                 link=p.link.strip() if normalise_url(p.link) else "",
                                 bullets=[b.text.strip() for b in p.bullets if b.text.strip()])
                       for p in profile.projects]
            sections.append(ViewSection(key, "entries", HEADINGS[key], entries=entries))
        elif key == "education" and profile.education:
            entries = [ViewEntry(heading=ed.institution.strip() or ed.degree.strip(), dates=ed.dates.strip(),
                                 subheading=_join(ed.degree if ed.institution.strip() else "", ed.location),
                                 bullets=[d.text.strip() for d in ed.details if d.text.strip()])
                       for ed in profile.education]
            sections.append(ViewSection(key, "entries", HEADINGS[key], entries=entries))
        elif key == "certifications" and config.include_certifications and profile.certifications:
            lines = [_join(ct.name, ct.issuer, ct.date) for ct in profile.certifications if ct.name.strip()]
            if lines:
                sections.append(ViewSection(key, "list", HEADINGS[key], lines=lines))
        elif key == "other" and config.include_other:
            for o in profile.other:
                lines = [i.text.strip() for i in o.items if i.text.strip()]
                if lines:
                    sections.append(ViewSection(key, "list", o.title.strip() or "Additional Information", lines=lines))
    return ResumeView(
        name=c.name.strip(),
        contact_items=[v.strip() for v in (c.phone, c.email, c.location) if v and v.strip()],
        email=c.email.strip(),
        links=[u.strip() for u in c.links if normalise_url(u)],
        sections=sections,
    )


def _context(view: ResumeView, config: ResumeConfig) -> dict[str, Any]:
    esc = escape_latex
    sep = r" \textbar{} "

    def contact(item: str) -> str:
        if item == view.email and escape_url(item):
            return rf"\href{{{escape_url(item)}}}{{{esc(item)}}}"
        return esc(item)

    def link(url: str) -> str:
        return rf"\href{{{escape_url(url)}}}{{{esc(display_url(url))}}}"

    sections: list[dict[str, Any]] = []
    for s in view.sections:
        sections.append({
            "kind": s.kind,
            "heading": esc(s.heading),
            "text": esc(s.text, multiline=True),
            "groups": [{"category": esc(cat), "skills": ", ".join(esc(i) for i in items)} for cat, items in s.groups],
            "entries": [{
                "heading": esc(e.heading), "dates": esc(e.dates), "subheading": esc(e.subheading),
                "link_url": escape_url(e.link) if e.link else "", "link_text": esc(display_url(e.link)) if e.link else "",
                "bullets": [esc(b) for b in e.bullets],
            } for e in s.entries],
            "lines": [esc(line) for line in s.lines],
        })
    title = " - ".join(p for p in (view.name, config.target_role.strip()) if p) or "Resume"
    return {
        "font_size": int(config.font_size),
        "paper": "a4" if config.paper == "a4" else "letter",
        "name": esc(view.name) or "Name",
        "pdf_title": esc(title),
        "contact_line": sep.join(contact(i) for i in view.contact_items),
        "link_line": sep.join(link(u) for u in view.links),
        "sections": sections,
    }


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string="((#", comment_end_string="#))",
        trim_blocks=True, lstrip_blocks=True, autoescape=False,
        undefined=StrictUndefined, keep_trailing_newline=True,
    )


def render_latex(profile: ResumeProfile, config: ResumeConfig) -> tuple[str, ResumeView]:
    view = build_view(profile, config)
    source = _environment().get_template(TEMPLATE_NAME).render(**_context(view, config))
    return re.sub(r"\n{3,}", "\n\n", source).lstrip("\n"), view
