"""Builds focused prompts, calls the provider and validates what comes back."""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import ValidationError

from ..lexicon import content_stems, term_in_text
from ..models import (
    SUMMARY_ID, MatchReport, Requirement, ResumeProfile, Suggestion, build_evidence,
)
from .provider import AIInvalidResponse, AIProvider
from .schemas import SUGGESTION_BATCH_NAME, SUGGESTION_BATCH_SCHEMA, AISuggestionBatch
from .validation import find_targets, validate_ai_suggestion

MAX_BULLETS_SENT = 24
MAX_REQUIREMENTS_SENT = 30
MAX_SUGGESTIONS = 12

SYSTEM_PROMPT = """You help a candidate tailor an existing resume to a job description.
You receive (1) job requirements with a match status and (2) resume items, each with an ID.
Every fact you may use is in those resume items. You have no other knowledge of the candidate.

What you may do:
- Rewrite an editable bullet or the summary so it is clearer, more concise and foregrounds work that is relevant to the requirements.
- Use the job description's terminology only where it accurately describes what the resume item already says.
- Reorder the entries of an editable skills group so the most relevant come first (same entries, no additions).

What you must never do:
- Add a technology, tool, skill, employer, project, responsibility, certification or degree that is not in the resume items.
- Add or change any number, percentage, duration, team size or metric.
- Raise seniority or ownership (for example "led", "managed", "architected", "expert") beyond what the item states.
- Present shared or supporting work as an individual achievement.
- Address a requirement marked "gap": true. Gaps stay gaps; do not write around them.
- Copy sentences from the job description.

Output rules:
- Only target items with "editable": true, using their exact "id" as target_id. One suggestion per target.
- proposed_text is plain text without markdown. For a skills group it is the comma-separated list.
- evidence_ids must list every resume item ID whose facts your wording relies on, including the target itself. Never invent IDs.
- requirement_ids lists the requirement IDs the change helps with.
- reason explains in one sentence what you changed and why.
- confidence is "high" only when the meaning is unchanged; use "low" when the user should double-check.
- If an item is already good, do not include it. Returning few or zero suggestions is acceptable.
- Return at most {max_suggestions} suggestions."""


def _relevance(text: str, requirements: list[Requirement]) -> float:
    stems = content_stems(text)
    score = 0.0
    for r in requirements:
        score += 2.0 * sum(1 for k in r.keywords if term_in_text(k, text))
        score += 0.5 * len(stems & content_stems(r.text))
    return score


def build_payload(profile: ResumeProfile, requirements: list[Requirement], report: Optional[MatchReport],
                  target_role: str, only_target: Optional[str] = None,
                  avoid: Optional[list[str]] = None) -> dict[str, Any]:
    """The minimal slice of resume + JD the model needs. Contact details are never included."""
    status = {m.requirement_id: m.status for m in (report.matches if report else [])}
    reqs = [r for r in requirements if r.category != "terminology"][:MAX_REQUIREMENTS_SENT]
    req_payload = [{"id": r.id, "text": r.text, "importance": r.importance,
                    "status": status.get(r.id, "unclear"), "gap": status.get(r.id) == "unsupported"} for r in reqs]

    targets = find_targets(profile)
    evidence = build_evidence(profile)
    bullets = [e for e in evidence if e.kind in ("experience_bullet", "project_bullet")]
    if only_target:
        keep = {only_target}
    else:
        ranked = sorted(bullets, key=lambda e: -_relevance(e.text, reqs))
        keep = {e.id for e in ranked[:MAX_BULLETS_SENT]} | {SUMMARY_ID} | {g.id for g in profile.skills}

    items: list[dict[str, Any]] = []
    if SUMMARY_ID in keep and not any(e.id == SUMMARY_ID for e in evidence):
        items.append({"id": SUMMARY_ID, "type": "summary", "context": "Professional summary (currently empty)",
                      "text": "", "editable": True})
    for e in evidence:
        editable = e.id in targets and e.id in keep
        if editable:
            items.append({"id": e.id, "type": e.kind, "context": e.context, "text": e.text, "editable": True})
        elif e.kind in ("experience", "project", "education", "certification", "skill", "summary"):
            # read-only context: headings and listed skills, so the model knows what is documented
            items.append({"id": e.id, "type": e.kind, "context": e.context, "text": e.text, "editable": False})
    payload: dict[str, Any] = {"target_role": target_role, "requirements": req_payload, "resume_items": items}
    if only_target:
        payload["task"] = (f"Write exactly one new suggestion for target_id '{only_target}'. "
                           "It must differ from every entry in previous_wordings.")
        payload["previous_wordings"] = avoid or []
    return payload


def _call(provider: AIProvider, payload: dict[str, Any]) -> AISuggestionBatch:
    data = provider.complete_json(
        system=SYSTEM_PROMPT.replace("{max_suggestions}", str(MAX_SUGGESTIONS)),
        user=json.dumps(payload, ensure_ascii=False),
        schema_name=SUGGESTION_BATCH_NAME,
        json_schema=SUGGESTION_BATCH_SCHEMA,
    )
    try:
        return AISuggestionBatch.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
        raise AIInvalidResponse(f"The model's answer did not match the required structure ({problems}). "
                                "Nothing was changed.") from exc


def _unsupported(report: Optional[MatchReport]) -> set[str]:
    return {m.requirement_id for m in (report.matches if report else []) if m.status == "unsupported"}


def generate_suggestions(provider: AIProvider, *, profile: ResumeProfile, requirements: list[Requirement],
                         report: Optional[MatchReport], jd_text: str, target_role: str) -> tuple[list[Suggestion], dict[str, Any]]:
    payload = build_payload(profile, requirements, report, target_role)
    batch = _call(provider, payload)
    out: list[Suggestion] = []
    seen: set[str] = set()
    for raw in batch.suggestions[:MAX_SUGGESTIONS * 2]:
        sug = validate_ai_suggestion(raw, profile=profile, requirements=requirements, jd_text=jd_text,
                                     unsupported_requirement_ids=_unsupported(report))
        if sug.status != "invalid" and sug.target_id in seen:
            sug.status, sug.invalid_reason = "invalid", "Rejected: the model proposed more than one change for this item."
        elif sug.status != "invalid":
            seen.add(sug.target_id)
        out.append(sug)
    meta = {"provider": provider.name, "model": provider.model,
            "resume_items_sent": len(payload["resume_items"]), "requirements_sent": len(payload["requirements"])}
    return out, meta


def regenerate_suggestion(provider: AIProvider, previous: Suggestion, *, profile: ResumeProfile,
                          requirements: list[Requirement], report: Optional[MatchReport], jd_text: str,
                          target_role: str) -> Suggestion:
    avoid = [t for t in [*previous.history, previous.proposed_text] if t]
    payload = build_payload(profile, requirements, report, target_role, only_target=previous.target_id, avoid=avoid)
    batch = _call(provider, payload)
    match = next((s for s in batch.suggestions if s.target_id == previous.target_id), None)
    if match is None:
        raise AIInvalidResponse("The model did not return a new wording for this item. Nothing was changed.")
    fresh = validate_ai_suggestion(match, profile=profile, requirements=requirements, jd_text=jd_text,
                                   unsupported_requirement_ids=_unsupported(report))
    if fresh.status == "invalid":
        raise AIInvalidResponse(f"The new wording was rejected by validation: {fresh.invalid_reason}")
    fresh.id = previous.id
    fresh.history = avoid
    return fresh
