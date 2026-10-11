"""Turn parsed sections (title + events) into a ResumeProfile plus human-readable warnings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from ..models import ResumeProfile
from . import heuristics as h


@dataclass
class ParsedSection:
    title: str
    events: list[h.Event]
    line: Optional[int] = None


class ParseResult(BaseModel):
    profile: ResumeProfile
    extracted_text: str = ""
    warnings: list[str] = Field(default_factory=list)


def assemble_profile(header_text: str, header_urls: list[str], sections: list[ParsedSection],
                     contact_overrides: Optional[dict[str, str]] = None) -> tuple[ResumeProfile, list[str]]:
    warnings: list[str] = []
    profile = ResumeProfile()
    profile.contact = h.extract_contact(header_text, header_urls)
    for key, value in (contact_overrides or {}).items():
        if value:
            setattr(profile.contact, key, value)

    for sec in sections:
        key = h.classify_section(sec.title)
        before = _count(profile)
        if key == "summary":
            text = h.make_summary(sec.events)
            profile.summary = (profile.summary + " " + text).strip()
        elif key == "skills":
            profile.skills.extend(h.make_skills(sec.events))
        elif key == "experience":
            profile.experience.extend(h.make_experience(r) for r in h.build_entries(sec.events))
        elif key == "projects":
            profile.projects.extend(h.make_project(r) for r in h.build_entries(sec.events))
        elif key == "education":
            profile.education.extend(h.make_education(r) for r in h.build_entries(sec.events))
        elif key == "certifications":
            profile.certifications.extend(h.make_certifications(sec.events))
        else:
            other = h.make_other(sec.title, sec.events, sec.line)
            if other:
                profile.other.append(other)
        if _count(profile) == before:
            warnings.append(f"Section '{sec.title}' was found but nothing could be extracted from it — add its content manually.")

    c = profile.contact
    if not c.name:
        warnings.append("Could not identify the candidate name in the document header.")
    if not c.email:
        warnings.append("Could not find an email address in the document header.")
    for e in profile.experience:
        if e.uncertain:
            label = " / ".join(p for p in (e.employer, e.title) if p) or "an entry"
            warnings.append(f"Experience entry '{label}': employer, job title or dates were assigned by guesswork — please verify.")
    for ed in profile.education:
        if ed.uncertain:
            warnings.append(f"Education entry '{ed.institution or ed.degree or '?'}': degree/institution assignment is uncertain — please verify.")
    for p in profile.projects:
        if p.uncertain:
            warnings.append("A project entry has no recognisable name — please verify.")
    if not sections:
        warnings.append("No section headings were recognised. The structured profile is probably incomplete.")
    return ResumeProfile.model_validate(profile.model_dump()), warnings


def _count(p: ResumeProfile) -> int:
    return (len(p.summary) + len(p.skills) + len(p.experience) + len(p.projects) + len(p.education)
            + len(p.certifications) + len(p.other))
