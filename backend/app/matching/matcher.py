"""Deterministic requirement-to-evidence matching.

A keyword appearing somewhere in the resume is not treated as proof. Evidence is graded:

* demonstrated — the term appears in an experience or project bullet (something the candidate did)
* claimed      — the term appears only in a skills list, summary, heading or certification
* related      — a neighbouring technology or overlapping wording appears, but not the term itself

and the requirement status follows from the weakest link.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..lexicon import canonical_term, content_stems, related_terms, term_in_text
from ..models import (
    EvidenceItem, MatchEvidence, MatchReport, MatchScore, Requirement, RequirementMatch, ResumeProfile,
    build_evidence,
)

_DEMONSTRATED_KINDS = {"experience_bullet", "project_bullet"}
_WEIGHT = {"must": 3, "important": 2, "nice": 1}
_CREDIT = {"supported": 1.0, "needs_confirmation": 0.5, "indirect": 0.25, "unsupported": 0.0}
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)", re.I)
_OR_RE = re.compile(r"\bor\b|/| and/or ", re.I)
_SCORED_CATEGORIES = {"required_skill", "preferred_skill", "responsibility", "experience", "qualification",
                      "technology"}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

SCORE_EXPLANATION = (
    "Weighted share of scored requirements with resume evidence. Each requirement is weighted by importance "
    "(must = 3, important = 2, nice-to-have = 1) and earns full credit when supported by explicit evidence, "
    "half credit when potentially supported, a quarter when only indirectly mentioned and none when "
    "unsupported. Unclear requirements and recurring-terminology entries are excluded. This is a rough "
    "estimate of documented overlap — it is not an ATS score and does not predict hiring outcomes."
)


def _excerpt(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _hits(term: str, evidence: list[EvidenceItem]) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    demonstrated = [e for e in evidence if e.kind in _DEMONSTRATED_KINDS and term_in_text(term, e.text)]
    claimed = [e for e in evidence if e.kind not in _DEMONSTRATED_KINDS and term_in_text(term, e.text)]
    return demonstrated, claimed


def estimate_years(profile: ResumeProfile, today: Optional[date] = None) -> Optional[float]:
    """Rough span covered by employment dates (overlaps merged). None when dates cannot be read."""
    today = today or date.today()
    spans: list[tuple[int, int]] = []
    for e in profile.experience:
        points = list(re.finditer(r"(?:([A-Za-z]{3})[a-z]*\.?\s+)?((?:19|20)\d{2})", e.dates))
        if not points:
            continue

        def months(m: re.Match[str], default_month: int) -> int:
            month = _MONTHS.get((m.group(1) or "").lower(), default_month)
            return int(m.group(2)) * 12 + month

        start = months(points[0], 1)
        if re.search(r"present|current|now|ongoing|today", e.dates, re.I):
            end = today.year * 12 + today.month
        elif len(points) > 1:
            end = months(points[1], 12)
        else:
            end = start + 11
        if end >= start:
            spans.append((start, end))
    if not spans:
        return None
    spans.sort()
    total, (cur_start, cur_end) = 0, spans[0]
    for start, end in spans[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    total += cur_end - cur_start + 1
    return round(total / 12, 1)


def match_requirement(req: Requirement, profile: ResumeProfile, evidence: list[EvidenceItem],
                      today: Optional[date] = None) -> RequirementMatch:
    keywords = [canonical_term(k) for k in req.keywords if k.strip()]
    found: dict[str, MatchEvidence] = {}
    matched: list[str] = []
    missing: list[str] = []
    demonstrated_terms: list[str] = []
    related_only: list[str] = []
    notes: list[str] = []

    def record(item: EvidenceItem, term: str, strength: str) -> None:
        entry = found.get(item.id)
        if entry is None:
            found[item.id] = MatchEvidence(evidence_id=item.id, excerpt=_excerpt(item.text), context=item.context,
                                           matched_terms=[term], strength=strength)  # type: ignore[arg-type]
        else:
            if term not in entry.matched_terms:
                entry.matched_terms.append(term)
            order = ["related", "claimed", "demonstrated"]
            if order.index(strength) > order.index(entry.strength):
                entry.strength = strength  # type: ignore[assignment]

    for term in keywords:
        demonstrated, claimed = _hits(term, evidence)
        if demonstrated or claimed:
            matched.append(term)
            if demonstrated:
                demonstrated_terms.append(term)
            for item in demonstrated[:3]:
                record(item, term, "demonstrated")
            for item in claimed[: (1 if demonstrated else 2)]:
                record(item, term, "claimed")
            continue
        neighbours = [(rel, e) for rel in sorted(related_terms(term)) for e in evidence if term_in_text(rel, e.text)]
        if neighbours:
            related_only.append(term)
            for rel, item in neighbours[:2]:
                record(item, f"{rel} (related to {term})", "related")
        else:
            missing.append(term)

    years = _YEARS_RE.search(req.text)
    status: str
    if req.category == "experience" and years:
        wanted = int(years.group(1))
        estimate = estimate_years(profile, today)
        for e in profile.experience:
            if e.dates:
                item = next(ev for ev in evidence if ev.id == e.id)
                record(item, e.dates, "claimed")
        if estimate is None:
            status = "unclear"
            notes.append("Employment dates could not be read, so years of experience cannot be estimated.")
        else:
            notes.append(f"Employment dates span roughly {estimate} year(s); the posting asks for {wanted}+. "
                         "Whether those years are relevant to this role is for you to judge.")
            status = "needs_confirmation" if estimate >= wanted else "unsupported"
            if keywords and not matched:
                status = "unsupported" if not related_only else "indirect"
    elif keywords:
        alternatives = bool(_OR_RE.search(req.text)) and len(keywords) > 1
        if alternatives and demonstrated_terms:
            status = "supported"
            notes.append("The posting lists alternatives; at least one is demonstrated in your experience.")
        elif len(demonstrated_terms) == len(keywords):
            status = "supported"
        elif len(matched) == len(keywords) or (alternatives and matched):
            status = "needs_confirmation"
            listed_only = [t for t in matched if t not in demonstrated_terms]
            notes.append("Listed in skills/summary but not shown in any experience or project bullet: "
                         + ", ".join(listed_only) + ".")
        elif matched and len(matched) * 2 >= len(keywords):
            status = "needs_confirmation"
            notes.append("Only part of this requirement is documented.")
        elif matched or related_only:
            status = "indirect"
        else:
            status = "unsupported"
        if related_only:
            notes.append("Related but not identical technology found for: " + ", ".join(related_only) + ".")
    else:
        wanted_stems = content_stems(req.text)
        best: list[tuple[int, EvidenceItem, set[str]]] = []
        for item in evidence:
            if item.kind in ("skill", "experience", "project"):
                continue
            overlap = wanted_stems & content_stems(item.text)
            if len(overlap) >= 2 and len(overlap) / max(len(wanted_stems), 1) >= 0.4:
                best.append((len(overlap), item, overlap))
        best.sort(key=lambda t: -t[0])
        if len(wanted_stems) < 2:
            status = "unclear"
            notes.append("This requirement has no concrete terms to check against the resume.")
        elif best:
            top = best[0][0]
            for _, item, overlap in best[:2]:
                record(item, ", ".join(sorted(overlap)), "related")
            if top / len(wanted_stems) >= 0.6 and top >= 3:
                status = "needs_confirmation"
                notes.append("Similar wording appears in the resume, but wording overlap alone is not proof.")
            else:
                status = "indirect"
        elif req.category == "qualification":
            status = "unclear"
            notes.append("Could not be checked automatically — confirm it yourself.")
        else:
            status = "unsupported"

    if req.category == "qualification" and status in ("unsupported", "indirect") and not keywords:
        edu = [ev for ev in evidence if ev.kind in ("education", "certification")]
        if edu and re.search(r"degree|bachelor|master|ph\.?d|diploma", req.text, re.I):
            for item in edu[:2]:
                record(item, "education", "claimed")
            status = "needs_confirmation"
            notes.append("Education is listed; confirm it satisfies this qualification.")

    return RequirementMatch(requirement_id=req.id, status=status, evidence=list(found.values()),  # type: ignore[arg-type]
                            matched_terms=matched, missing_terms=missing + related_only, note=" ".join(notes))


def build_match_report(requirements: list[Requirement], profile: ResumeProfile,
                       today: Optional[date] = None) -> MatchReport:
    evidence = build_evidence(profile)
    matches = [match_requirement(r, profile, evidence, today) for r in requirements]
    by_id = {r.id: r for r in requirements}
    earned = possible = 0.0
    counts = {k: 0 for k in ("supported", "needs_confirmation", "indirect", "unsupported", "unclear")}
    for m in matches:
        counts[m.status] += 1
        req = by_id[m.requirement_id]
        if m.status == "unclear" or req.category not in _SCORED_CATEGORIES:
            continue
        weight = _WEIGHT[req.importance]
        possible += weight
        earned += weight * _CREDIT[m.status]
    value = round(100 * earned / possible) if possible else 0
    return MatchReport(matches=matches, score=MatchScore(
        value=value, label="Heuristic estimate — not an ATS score", explanation=SCORE_EXPLANATION, counts=counts))

