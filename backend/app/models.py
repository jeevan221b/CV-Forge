"""Domain models shared by parsing, matching, tailoring, rendering and the API."""
from __future__ import annotations

import re
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Origin = Literal["document", "user"]

SECTION_KEYS = ("summary", "skills", "experience", "projects", "education", "certifications", "other")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Traced(BaseModel):
    """Anything that carries a fact. `origin` records whether it came from the uploaded
    document or was typed/confirmed by the user; `uncertain` marks low-confidence parses."""

    id: str = ""
    origin: Origin = "document"
    source_line: Optional[int] = None
    uncertain: bool = False


class Bullet(Traced):
    text: str = ""


class Contact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)


class SkillGroup(Traced):
    category: str = ""
    items: list[str] = Field(default_factory=list)


class Experience(Traced):
    employer: str = ""
    title: str = ""
    location: str = ""
    dates: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class Project(Traced):
    name: str = ""
    tech: str = ""
    dates: str = ""
    link: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class Education(Traced):
    institution: str = ""
    degree: str = ""
    location: str = ""
    dates: str = ""
    details: list[Bullet] = Field(default_factory=list)


class Certification(Traced):
    name: str = ""
    issuer: str = ""
    date: str = ""


class OtherSection(Traced):
    title: str = ""
    items: list[Bullet] = Field(default_factory=list)


_ID_PREFIX = {
    "skills": "skl",
    "experience": "exp",
    "projects": "prj",
    "education": "edu",
    "certifications": "crt",
    "other": "oth",
}


class ResumeProfile(BaseModel):
    contact: Contact = Field(default_factory=Contact)
    summary: str = ""
    summary_origin: Origin = "document"
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    other: list[OtherSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ensure_unique_ids(self) -> "ResumeProfile":
        seen: set[str] = set()

        def fix(obj: Traced, prefix: str) -> None:
            if not obj.id or obj.id in seen or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", obj.id):
                obj.id = new_id(prefix)
            seen.add(obj.id)

        for key, prefix in _ID_PREFIX.items():
            for entry in getattr(self, key):
                fix(entry, prefix)
                for child_attr in ("bullets", "details", "items"):
                    children = getattr(entry, child_attr, None)
                    if children and isinstance(children[0], Bullet):
                        for child in children:
                            fix(child, "blt")
        return self


# ---------------------------------------------------------------- evidence


EvidenceKind = Literal[
    "summary", "skill", "experience", "experience_bullet", "project", "project_bullet",
    "education", "certification", "other",
]


class EvidenceItem(BaseModel):
    id: str
    kind: EvidenceKind
    text: str
    context: str = ""
    origin: Origin = "document"


SUMMARY_ID = "summary"


def build_evidence(profile: ResumeProfile) -> list[EvidenceItem]:
    """Flatten a profile into addressable evidence. IDs are the profile's own stable IDs."""
    out: list[EvidenceItem] = []
    if profile.summary.strip():
        out.append(EvidenceItem(id=SUMMARY_ID, kind="summary", text=profile.summary.strip(),
                                context="Professional summary", origin=profile.summary_origin))
    for g in profile.skills:
        if g.items:
            out.append(EvidenceItem(id=g.id, kind="skill", text=", ".join(g.items),
                                    context=f"Skills: {g.category or 'Skills'}", origin=g.origin))
    for e in profile.experience:
        label = ", ".join(p for p in (e.title, e.employer) if p)
        header = label + (f" ({e.dates})" if e.dates else "")
        out.append(EvidenceItem(id=e.id, kind="experience", text=header, context="Work experience", origin=e.origin))
        for b in e.bullets:
            if b.text.strip():
                out.append(EvidenceItem(id=b.id, kind="experience_bullet", text=b.text.strip(),
                                        context=label, origin=b.origin))
    for p in profile.projects:
        header = p.name + (f" ({p.tech})" if p.tech else "")
        out.append(EvidenceItem(id=p.id, kind="project", text=header, context="Project", origin=p.origin))
        for b in p.bullets:
            if b.text.strip():
                out.append(EvidenceItem(id=b.id, kind="project_bullet", text=b.text.strip(),
                                        context=f"Project: {p.name}", origin=b.origin))
    for ed in profile.education:
        text = ", ".join(p for p in (ed.degree, ed.institution) if p)
        out.append(EvidenceItem(id=ed.id, kind="education", text=text, context="Education", origin=ed.origin))
        for d in ed.details:
            if d.text.strip():
                out.append(EvidenceItem(id=d.id, kind="education", text=d.text.strip(),
                                        context=f"Education: {ed.institution}", origin=d.origin))
    for c in profile.certifications:
        text = c.name + (f" ({c.issuer})" if c.issuer else "")
        out.append(EvidenceItem(id=c.id, kind="certification", text=text, context="Certification", origin=c.origin))
    for s in profile.other:
        for it in s.items:
            if it.text.strip():
                out.append(EvidenceItem(id=it.id, kind="other", text=it.text.strip(),
                                        context=s.title or "Other", origin=it.origin))
    return out


def profile_corpus(profile: ResumeProfile) -> str:
    """All fact-bearing text in the profile, used to decide whether a term is documented at all."""
    return "\n".join(e.text for e in build_evidence(profile))


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def profile_issues(profile: ResumeProfile) -> list[str]:
    """Deterministic completeness checks shown before a profile is treated as verified."""
    issues: list[str] = []
    c = profile.contact
    if not c.name.strip():
        issues.append("Contact name is missing.")
    if not c.email.strip():
        issues.append("Email address is missing.")
    elif not _EMAIL_RE.match(c.email.strip()):
        issues.append(f"Email address '{c.email}' does not look valid.")
    if not profile.experience and not profile.projects:
        issues.append("No work experience or projects were found.")
    for e in profile.experience:
        label = e.employer or e.title or "an experience entry"
        if not e.employer.strip():
            issues.append(f"Employer name is missing for {label}.")
        if not e.title.strip():
            issues.append(f"Job title is missing for {label}.")
        if not e.dates.strip():
            issues.append(f"Employment dates are missing for {label}.")
        if e.uncertain:
            issues.append(f"Field assignment for {label} was uncertain — check employer, title and dates.")
    for p in profile.projects:
        if not p.name.strip():
            issues.append("A project has no name.")
    for ed in profile.education:
        if not ed.institution.strip() or not ed.degree.strip():
            issues.append(f"Education entry '{ed.institution or ed.degree or '?'}' is missing a degree or institution.")
    if not profile.education:
        issues.append("No education entries were found.")
    if not profile.skills:
        issues.append("No skills were found.")
    return issues


# ---------------------------------------------------------------- job description


ReqCategory = Literal[
    "required_skill", "preferred_skill", "responsibility", "experience",
    "qualification", "technology", "terminology",
]
Importance = Literal["must", "important", "nice"]


class Requirement(BaseModel):
    id: str = ""
    text: str
    category: ReqCategory = "required_skill"
    importance: Importance = "important"
    keywords: list[str] = Field(default_factory=list)
    origin: Literal["extracted", "user"] = "extracted"


class JDAnalysis(BaseModel):
    job_title: str = ""
    employer: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids(self) -> "JDAnalysis":
        seen: set[str] = set()
        for r in self.requirements:
            if not r.id or r.id in seen:
                r.id = new_id("req")
            seen.add(r.id)
        return self


MatchStatus = Literal["supported", "needs_confirmation", "indirect", "unsupported", "unclear"]

STATUS_LABELS: dict[str, str] = {
    "supported": "Supported by explicit evidence",
    "needs_confirmation": "Potentially supported, needs confirmation",
    "indirect": "Mentioned only indirectly",
    "unsupported": "Not supported by the current resume",
    "unclear": "Not applicable or unclear",
}


class MatchEvidence(BaseModel):
    evidence_id: str
    excerpt: str
    context: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    strength: Literal["demonstrated", "claimed", "related"] = "demonstrated"


class RequirementMatch(BaseModel):
    requirement_id: str
    status: MatchStatus
    evidence: list[MatchEvidence] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)
    note: str = ""


class MatchScore(BaseModel):
    value: int
    label: str = "Heuristic estimate"
    explanation: str = ""
    counts: dict[str, int] = Field(default_factory=dict)


class MatchReport(BaseModel):
    matches: list[RequirementMatch] = Field(default_factory=list)
    score: MatchScore = Field(default_factory=lambda: MatchScore(value=0))


# ---------------------------------------------------------------- tailoring


class Flag(BaseModel):
    code: str
    severity: Literal["info", "warning", "blocker"] = "warning"
    message: str
    terms: list[str] = Field(default_factory=list)


SuggestionStatus = Literal["pending", "accepted", "modified", "rejected", "invalid"]


class Suggestion(BaseModel):
    id: str = ""
    target_id: str
    target_kind: Literal["summary", "bullet", "skills"] = "bullet"
    target_label: str = ""
    original_text: str = ""
    proposed_text: str = ""
    final_text: Optional[str] = None  # set when the user edits the wording
    reason: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    flags: list[Flag] = Field(default_factory=list)
    requires_confirmation: bool = False
    confirmed: bool = False
    status: SuggestionStatus = "pending"
    invalid_reason: str = ""
    history: list[str] = Field(default_factory=list)  # earlier wordings, for "another suggestion"

    @property
    def applied_text(self) -> Optional[str]:
        if self.status == "accepted":
            return self.proposed_text
        if self.status == "modified":
            return self.final_text
        return None


class ResumeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_role: str = ""
    section_order: list[str] = Field(default_factory=lambda: list(SECTION_KEYS))
    include_summary: bool = True
    include_projects: bool = True
    include_certifications: bool = True
    include_other: bool = True
    prioritized_skills: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=2, ge=1, le=6)
    paper: Literal["a4", "letter"] = "letter"
    font_size: Literal[10, 11, 12] = 11

    @model_validator(mode="after")
    def _normalise_order(self) -> "ResumeConfig":
        order = [s for i, s in enumerate(self.section_order) if s in SECTION_KEYS and s not in self.section_order[:i]]
        self.section_order = order + [s for s in SECTION_KEYS if s not in order]
        return self
