"""Deterministic checks applied to every AI suggestion and every user edit.

Nothing here asks a model whether a model was truthful. A suggestion is compared with the
text it replaces, the evidence it cites and the whole master profile; anything new that is
not backed by the profile is flagged and needs explicit confirmation, and suggestions with
no valid evidence at all are rejected outright.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from ..lexicon import canonical_term, find_terms, normalize_ws, term_in_text
from ..models import (
    SUMMARY_ID, EvidenceItem, Flag, Requirement, ResumeProfile, Suggestion, build_evidence, new_id,
    profile_corpus,
)
from .schemas import AISuggestion

_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.'/-]*")
_SENIORITY = ["led", "lead", "leading", "managed", "managing", "headed", "directed", "owned", "spearheaded",
              "architected", "principal", "senior", "expert", "expertise", "mastery", "extensive", "pioneered",
              "single-handedly", "independently", "solely", "drove", "championed", "orchestrated", "oversaw",
              "supervised", "mentored", "founded", "chief", "head"]
_TEAM_RE = re.compile(r"\b(team|collaborat\w*|worked with|working with|contribut\w*|participat\w*|assist\w*|"
                      r"helped|supported|alongside|together with|pair\w*|co-\w+)\b", re.I)
_SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+)([A-Z][A-Za-z0-9+#.'/-]*)")


@dataclass
class Target:
    kind: str  # summary | bullet | skills
    label: str
    text: str


def find_targets(profile: ResumeProfile) -> dict[str, Target]:
    """Everything the AI is allowed to rewrite. Employers, titles, dates, degrees, institutions,
    certification and project names are deliberately absent, so they can never be an AI target."""
    targets: dict[str, Target] = {SUMMARY_ID: Target("summary", "Professional summary", profile.summary.strip())}
    for g in profile.skills:
        targets[g.id] = Target("skills", f"Skills — {g.category or 'Skills'}", ", ".join(g.items))
    for e in profile.experience:
        label = ", ".join(p for p in (e.title, e.employer) if p) or "Experience"
        for b in e.bullets:
            targets[b.id] = Target("bullet", label, b.text.strip())
    for p in profile.projects:
        for b in p.bullets:
            targets[b.id] = Target("bullet", f"Project — {p.name}", b.text.strip())
    return targets


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "").rstrip(".") for m in _NUMBER_RE.finditer(text)}


def _words(text: str) -> set[str]:
    return {w.lower().strip(".'") for w in _WORD_RE.findall(text)}


def _split_skills(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s*[,;|]\s*(?![^()]*\))", text) if p.strip()]


def _shared_run(a: str, b: str, length: int = 7) -> Optional[str]:
    """Longest-enough word sequence that appears verbatim in both texts."""
    wa = re.findall(r"[a-z0-9']+", a.lower())
    wb = " ".join(re.findall(r"[a-z0-9']+", b.lower()))
    for i in range(len(wa) - length + 1):
        run = " ".join(wa[i: i + length])
        if run in wb:
            return run
    return None


def check_text(*, kind: str, original: str, proposed: str, cited: list[str], corpus: str,
               jd_keywords: list[str], jd_text: str) -> list[Flag]:
    """Compare a proposed wording with what the resume actually documents."""
    flags: list[Flag] = []
    basis = "\n".join([original, *cited])

    if kind == "skills":
        before = {canonical_term(s).lower(): s for s in _split_skills(original)}
        after = {canonical_term(s).lower(): s for s in _split_skills(proposed)}
        added = [v for k, v in after.items() if k not in before]
        removed = [v for k, v in before.items() if k not in after]
        undocumented = [s for s in added if not term_in_text(s, corpus)]
        elsewhere = [s for s in added if s not in undocumented]
        if undocumented:
            flags.append(Flag(code="skill_not_in_resume", severity="blocker", terms=undocumented,
                              message="Adds skills that appear nowhere in your master resume. "
                                      "Only confirm if you genuinely have them."))
        if elsewhere:
            flags.append(Flag(code="skill_moved", severity="warning", terms=elsewhere,
                              message="Adds skills to this group that are documented elsewhere in your resume."))
        if removed:
            flags.append(Flag(code="skill_removed", severity="warning", terms=removed,
                              message="Removes skills from this group."))
        return flags

    new_numbers = sorted(_numbers(proposed) - _numbers(basis))
    if new_numbers:
        flags.append(Flag(code="new_number", severity="blocker", terms=new_numbers,
                          message="Contains numbers or metrics that are not in the original text or cited evidence."))
    lost_numbers = sorted(_numbers(original) - _numbers(proposed))
    if lost_numbers:
        flags.append(Flag(code="number_removed", severity="warning", terms=lost_numbers,
                          message="Drops numbers that were in the original text."))

    candidates = list(dict.fromkeys([*find_terms(proposed), *(k for k in jd_keywords if term_in_text(k, proposed))]))
    new_terms = [t for t in candidates if not term_in_text(t, basis)]
    undocumented = [t for t in new_terms if not term_in_text(t, corpus)]
    elsewhere = [t for t in new_terms if t not in undocumented]
    if undocumented:
        flags.append(Flag(code="unsupported_claim", severity="blocker", terms=undocumented,
                          message="Mentions skills or job-description terms that appear nowhere in your master resume."))
    if elsewhere:
        flags.append(Flag(code="term_from_elsewhere", severity="warning", terms=elsewhere,
                          message="Mentions skills documented elsewhere in your resume but not in this item or its "
                                  "cited evidence. Confirm they really apply here."))

    corpus_words = _words(corpus) | _words(original)
    sentence_starts = {m.group(1) for m in _SENTENCE_START.finditer(proposed)}
    flagged = {t.lower() for t in new_terms}
    unfamiliar: list[str] = []
    for word in _WORD_RE.findall(proposed):
        bare = word.strip(".'")
        looks_named = bare[:1].isupper() or any(c.isupper() for c in bare[1:]) or any(c.isdigit() for c in bare)
        if not looks_named or bare.lower() in corpus_words or bare.lower() in flagged:
            continue
        if bare in sentence_starts and not any(c.isupper() or c.isdigit() for c in bare[1:]):
            continue  # ordinary capitalised first word of a sentence
        if bare not in unfamiliar:
            unfamiliar.append(bare)
    if unfamiliar:
        flags.append(Flag(code="unfamiliar_term", severity="warning", terms=unfamiliar,
                          message="Introduces names or acronyms that do not occur anywhere in your master resume."))

    basis_words = _words(basis)
    inflated = [w for w in _SENIORITY if re.search(rf"\b{re.escape(w)}\b", proposed, re.I) and w not in basis_words]
    if inflated:
        flags.append(Flag(code="seniority_language", severity="warning", terms=inflated,
                          message="Uses leadership or seniority wording that the original text does not contain."))

    if original and _TEAM_RE.search(original) and not _TEAM_RE.search(proposed):
        flags.append(Flag(code="team_to_individual", severity="warning",
                          message="The original describes shared or supporting work; the new wording may read as an "
                                  "individual achievement."))

    run = _shared_run(proposed, jd_text)
    if run and run not in " ".join(re.findall(r"[a-z0-9']+", original.lower())):
        flags.append(Flag(code="copied_from_jd", severity="warning", terms=[run],
                          message="Repeats a phrase from the job description word for word."))

    if not original:
        flags.append(Flag(code="new_content", severity="warning",
                          message="This is new text rather than a rewrite. Check every statement against your experience."))
    return flags


def validate_ai_suggestion(raw: AISuggestion, *, profile: ResumeProfile, requirements: list[Requirement],
                           jd_text: str, unsupported_requirement_ids: Optional[set[str]] = None) -> Suggestion:
    """Turn one model suggestion into a reviewable Suggestion, or mark it invalid."""
    targets = find_targets(profile)
    evidence = {e.id: e for e in build_evidence(profile)}
    known_reqs = {r.id for r in requirements}
    sug = Suggestion(id=new_id("sug"), target_id=raw.target_id, proposed_text=normalize_ws(raw.proposed_text),
                     reason=normalize_ws(raw.reason), confidence=raw.confidence)

    target = targets.get(raw.target_id)
    if target is None:
        sug.status, sug.invalid_reason = "invalid", (
            "The model tried to change something that is not an editable summary, skills group or bullet "
            "(or referenced an ID that does not exist). Protected fields cannot be changed by AI.")
        return sug
    sug.target_kind, sug.target_label, sug.original_text = target.kind, target.label, target.text  # type: ignore[assignment]

    valid_evidence = [i for i in dict.fromkeys(raw.evidence_ids) if i in evidence]
    bogus_evidence = [i for i in dict.fromkeys(raw.evidence_ids) if i not in evidence]
    sug.evidence_ids = valid_evidence
    sug.requirement_ids = [i for i in dict.fromkeys(raw.requirement_ids) if i in known_reqs]
    bogus_reqs = [i for i in dict.fromkeys(raw.requirement_ids) if i not in known_reqs]

    if not valid_evidence:
        sug.status, sug.invalid_reason = "invalid", (
            "Rejected: the model did not cite any evidence that exists in your master resume"
            + (f" (it referenced unknown IDs: {', '.join(bogus_evidence[:5])})." if bogus_evidence else "."))
        return sug
    if normalize_ws(sug.proposed_text).lower() == normalize_ws(sug.original_text).lower():
        sug.status, sug.invalid_reason = "invalid", "Rejected: the proposed text is identical to the original."
        return sug

    sug.flags = _flags_for(sug, sug.proposed_text, profile, evidence, requirements, jd_text)
    if bogus_evidence:
        sug.flags.insert(0, Flag(code="unknown_evidence_id", severity="warning", terms=bogus_evidence[:8],
                                 message="The model cited evidence IDs that do not exist; they were discarded."))
    if bogus_reqs:
        sug.flags.append(Flag(code="unknown_requirement_id", severity="info", terms=bogus_reqs[:8],
                              message="The model referenced requirement IDs that do not exist; they were discarded."))
    gaps = [i for i in sug.requirement_ids if i in (unsupported_requirement_ids or set())]
    if gaps:
        sug.flags.append(Flag(code="targets_gap", severity="warning", terms=gaps,
                              message="Linked to a requirement your resume does not support. Rewording cannot close a "
                                      "genuine gap — make sure this does not imply experience you lack."))
    sug.requires_confirmation = any(f.severity != "info" for f in sug.flags)
    return sug


def _flags_for(sug: Suggestion, text: str, profile: ResumeProfile, evidence: dict[str, EvidenceItem],
               requirements: list[Requirement], jd_text: str) -> list[Flag]:
    cited = [evidence[i].text for i in sug.evidence_ids if i in evidence]
    jd_keywords = list(dict.fromkeys(k for r in requirements for k in r.keywords))
    return check_text(kind=sug.target_kind, original=sug.original_text, proposed=text, cited=cited,
                      corpus=profile_corpus(profile), jd_keywords=jd_keywords, jd_text=jd_text)


def revalidate_user_text(sug: Suggestion, text: str, *, profile: ResumeProfile, requirements: list[Requirement],
                         jd_text: str) -> list[Flag]:
    """Flags for wording the user typed. Same checks as for AI text; the user can confirm them."""
    evidence = {e.id: e for e in build_evidence(profile)}
    return _flags_for(sug, normalize_ws(text), profile, evidence, requirements, jd_text)


def apply_suggestions(profile: ResumeProfile, suggestions: list[Suggestion]) -> ResumeProfile:
    """Master snapshot + approved changes = draft. Unapproved suggestions never touch the draft."""
    draft = deepcopy(profile)
    approved = {s.target_id: s.applied_text for s in suggestions
                if s.status in ("accepted", "modified") and s.applied_text
                and (not s.requires_confirmation or s.confirmed)}
    if not approved:
        return draft
    if SUMMARY_ID in approved:
        draft.summary = approved[SUMMARY_ID]
    for g in draft.skills:
        if g.id in approved:
            g.items = _split_skills(approved[g.id])
    for entry in [*draft.experience, *draft.projects]:
        for b in entry.bullets:
            if b.id in approved:
                b.text = approved[b.id]
    return draft
