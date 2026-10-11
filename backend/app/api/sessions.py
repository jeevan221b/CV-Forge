"""Tailoring sessions: JD analysis, matching, AI suggestions, review, generation, validation, export."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from typing import Any, Literal, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..ai.provider import AINotConfigured
from ..ai.groq_client import SETUP_HINT
from ..ai.tailoring import generate_suggestions, regenerate_suggestion
from ..ai.validation import apply_suggestions, revalidate_user_text
from ..ats.report_md import render_match_report
from ..ats.validate import qualification_report, validate_pdf
from ..jd.analyzer import analyze_jd, normalise_keywords
from ..latex.compiler import compile_latex, detect_toolchain, sha256_text
from ..latex.renderer import render_latex
from ..lexicon import find_terms, normalize_ws
from ..matching.matcher import build_match_report
from ..models import (
    STATUS_LABELS, JDAnalysis, Requirement, ResumeConfig, ResumeProfile, Suggestion, build_evidence,
)
from ..storage.store import SessionData, Store, now_iso
from .deps import check_id, clean_name, fail, provider_of, settings_of, slug, store_of

router = APIRouter()
log = logging.getLogger("cvforge.sessions")

MAX_JD_CHARS = 30_000
_STRUCTURAL_FLAGS = {"unknown_evidence_id", "unknown_requirement_id", "targets_gap"}


# ---------------------------------------------------------------- helpers


def _load(request: Request, session_id: str) -> tuple[Store, dict, SessionData]:
    store = store_of(request)
    check_id(store, "session", session_id)
    found = store.get_session(session_id)
    if not found:
        fail(404, "not_found", "Session not found.")
    return store, found[0], found[1]


def _draft(data: SessionData) -> ResumeProfile:
    return apply_suggestions(data.profile, data.suggestions)


def _fingerprint(data: SessionData) -> str:
    blob = _draft(data).model_dump_json() + data.config.model_dump_json()
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _tex_path(store: Store, session_id: str):
    return store.session_dir(session_id) / "resume.tex"


def _pdf_path(store: Store, session_id: str):
    return store.session_dir(session_id) / "resume.pdf"


def _clear_outputs(store: Store, session_id: str, data: SessionData) -> None:
    data.generated = data.compile = data.validation = None
    shutil.rmtree(store.session_dir(session_id), ignore_errors=True)


def _payload(store: Store, meta: dict, data: SessionData) -> dict[str, Any]:
    out = {**meta, **data.model_dump()}
    out["draft"] = _draft(data).model_dump()
    out["evidence"] = [e.model_dump() for e in build_evidence(data.profile)]
    out["status_labels"] = STATUS_LABELS
    tex = _tex_path(store, meta["id"])
    out["tex"] = tex.read_text("utf-8") if data.generated and tex.is_file() else None
    if data.generated:
        out["generated"] = {**data.generated, "stale": data.generated.get("fingerprint") != _fingerprint(data)}
    out["has_pdf"] = bool(data.compile and data.compile.get("ok") and _pdf_path(store, meta["id"]).is_file())
    counts = {k: 0 for k in ("pending", "accepted", "modified", "rejected", "invalid")}
    for s in data.suggestions:
        counts[s.status] += 1
    out["suggestion_counts"] = counts
    return out


def _save(store: Store, meta: dict, data: SessionData, **kw: Any) -> dict[str, Any]:
    store.save_session(meta["id"], data, **kw)
    found = store.get_session(meta["id"])
    assert found
    return _payload(store, found[0], found[1])


def _rematch(data: SessionData) -> None:
    if data.analysis:
        data.match = build_match_report(data.analysis.requirements, data.profile)


def _refresh_flags(sug: Suggestion, text: str, data: SessionData) -> None:
    reqs = data.analysis.requirements if data.analysis else []
    kept = [f for f in sug.flags if f.code in _STRUCTURAL_FLAGS]
    sug.flags = kept + revalidate_user_text(sug, text, profile=data.profile, requirements=reqs, jd_text=data.jd_text)
    sug.requires_confirmation = any(f.severity != "info" for f in sug.flags)


# ---------------------------------------------------------------- CRUD


class SessionCreate(BaseModel):
    resume_id: str


@router.get("/sessions")
def list_sessions(request: Request) -> list[dict]:
    return store_of(request).list_sessions()


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, request: Request) -> dict:
    store = store_of(request)
    check_id(store, "resume", body.resume_id)
    resume = store.get_resume(body.resume_id)
    if not resume:
        fail(404, "not_found", "Resume not found.")
    session_id = store.create_session(resume)
    meta, data = store.get_session(session_id)  # type: ignore[misc]
    return _payload(store, meta, data)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    return _payload(store, meta, data)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> dict:
    store, _meta, _data = _load(request, session_id)
    store.delete_session(session_id)
    return {"deleted": True}


# ---------------------------------------------------------------- JD + requirements


class JDInput(BaseModel):
    jd_text: str = Field(min_length=1, max_length=MAX_JD_CHARS)
    job_title: Optional[str] = None
    employer: Optional[str] = None


@router.put("/sessions/{session_id}/jd")
def set_jd(session_id: str, body: JDInput, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    if not body.jd_text.strip():
        fail(400, "empty_jd", "Paste the job description first.")
    data.jd_text = body.jd_text
    data.analysis = analyze_jd(body.jd_text)
    if body.job_title and body.job_title.strip():
        data.analysis.job_title = clean_name(body.job_title, "")
    if body.employer and body.employer.strip():
        data.analysis.employer = clean_name(body.employer, "")
    _rematch(data)
    data.suggestions, data.ai_meta = [], {}  # suggestions refer to the previous requirement IDs
    _clear_outputs(store, session_id, data)
    if not data.config.target_role:
        data.config.target_role = data.analysis.job_title
    return _save(store, meta, data, job_title=data.analysis.job_title, employer=data.analysis.employer)


class RequirementsInput(BaseModel):
    job_title: str = ""
    employer: str = ""
    requirements: list[Requirement] = Field(max_length=200)


@router.put("/sessions/{session_id}/requirements")
def set_requirements(session_id: str, body: RequirementsInput, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    if data.analysis is None:
        fail(409, "no_jd", "Analyse a job description first.")
    previous = {r.id: r for r in data.analysis.requirements}
    cleaned: list[Requirement] = []
    for r in body.requirements:
        r.text = normalize_ws(r.text)
        if not r.text:
            continue
        old = previous.get(r.id)
        if old is None or old.text != r.text or old.keywords != r.keywords:
            r.origin = "user"
        r.keywords = normalise_keywords(r.keywords) if r.keywords else (find_terms(r.text) if old is None else [])
        cleaned.append(r)
    data.analysis = JDAnalysis(job_title=clean_name(body.job_title, ""), employer=clean_name(body.employer, ""),
                               requirements=cleaned, notes=data.analysis.notes)
    _rematch(data)
    known = {r.id for r in data.analysis.requirements}
    for s in data.suggestions:
        s.requirement_ids = [i for i in s.requirement_ids if i in known]
    return _save(store, meta, data, job_title=data.analysis.job_title, employer=data.analysis.employer)


# ---------------------------------------------------------------- AI suggestions


def _require_ai(request: Request) -> None:
    provider = provider_of(request)
    if not provider.is_configured():
        raise AINotConfigured(SETUP_HINT)
    if not store_of(request).get_settings()["ai_consent"]:
        fail(403, "consent_required",
             "AI tailoring sends resume and job-description content to Groq. Give consent before the first request.")


@router.post("/sessions/{session_id}/suggestions/generate")
def generate(session_id: str, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    if data.analysis is None or not data.analysis.requirements:
        fail(409, "no_jd", "Analyse a job description before requesting suggestions.")
    _require_ai(request)
    suggestions, ai_meta = generate_suggestions(
        provider_of(request), profile=data.profile, requirements=data.analysis.requirements, report=data.match,
        jd_text=data.jd_text, target_role=data.config.target_role or data.analysis.job_title)
    data.suggestions = suggestions
    data.ai_meta = {**ai_meta, "generated_at": now_iso()}
    log.info("suggestions generated session=%s total=%s invalid=%s", session_id, len(suggestions),
             sum(1 for s in suggestions if s.status == "invalid"))
    return _save(store, meta, data)


def _find(data: SessionData, suggestion_id: str) -> Suggestion:
    for s in data.suggestions:
        if s.id == suggestion_id:
            return s
    fail(404, "not_found", "Suggestion not found.")


class Decision(BaseModel):
    action: Literal["accept", "reject", "edit", "reset"]
    text: Optional[str] = Field(default=None, max_length=1500)
    confirm: bool = False


@router.post("/sessions/{session_id}/suggestions/{suggestion_id}/decision")
def decide(session_id: str, suggestion_id: str, body: Decision, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    sug = _find(data, suggestion_id)
    if sug.status == "invalid":
        fail(409, "invalid_suggestion", "This suggestion was rejected by validation and cannot be applied.")

    def need_confirmation() -> None:
        if sug.requires_confirmation and not body.confirm:
            fail(409, "confirmation_required",
                 "This wording contains points that could not be verified against your master resume. "
                 "Confirm that they are true before it can enter the draft.",
                 flags=[f.model_dump() for f in sug.flags])

    if body.action == "accept":
        _refresh_flags(sug, sug.proposed_text, data)
        need_confirmation()
        sug.status, sug.final_text, sug.confirmed = "accepted", None, sug.requires_confirmation
    elif body.action == "edit":
        text = normalize_ws(body.text or "")
        if not text:
            fail(400, "empty_text", "The edited text is empty. Reject the suggestion instead.")
        if text == normalize_ws(sug.original_text):
            fail(400, "unchanged", "The edited text is identical to the original. Reject the suggestion instead.")
        _refresh_flags(sug, text, data)
        need_confirmation()
        sug.status, sug.final_text, sug.confirmed = "modified", text, sug.requires_confirmation
    elif body.action == "reject":
        sug.status, sug.final_text, sug.confirmed = "rejected", None, False
    else:
        _refresh_flags(sug, sug.proposed_text, data)
        sug.status, sug.final_text, sug.confirmed = "pending", None, False
    return _save(store, meta, data)


@router.post("/sessions/{session_id}/suggestions/{suggestion_id}/regenerate")
def regenerate(session_id: str, suggestion_id: str, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    sug = _find(data, suggestion_id)
    if data.analysis is None:
        fail(409, "no_jd", "Analyse a job description first.")
    if sug.status == "invalid":
        fail(409, "invalid_suggestion", "This suggestion was rejected by validation.")
    _require_ai(request)
    fresh = regenerate_suggestion(
        provider_of(request), sug, profile=data.profile, requirements=data.analysis.requirements,
        report=data.match, jd_text=data.jd_text, target_role=data.config.target_role or data.analysis.job_title)
    data.suggestions = [fresh if s.id == sug.id else s for s in data.suggestions]
    return _save(store, meta, data)


@router.post("/sessions/{session_id}/suggestions/reset")
def reset_all(session_id: str, request: Request) -> dict:
    """Return the draft to the original master content. Suggestions stay available for review."""
    store, meta, data = _load(request, session_id)
    for s in data.suggestions:
        if s.status != "invalid":
            _refresh_flags(s, s.proposed_text, data)
            s.status, s.final_text, s.confirmed = "pending", None, False
    return _save(store, meta, data)


# ---------------------------------------------------------------- configure / generate / compile


@router.put("/sessions/{session_id}/config")
def set_config(session_id: str, body: ResumeConfig, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    body.target_role = clean_name(body.target_role, "", 120)
    body.prioritized_skills = [clean_name(s, "", 60) for s in body.prioritized_skills if s.strip()][:40]
    data.config = body
    return _save(store, meta, data)


@router.post("/sessions/{session_id}/generate")
def generate_tex(session_id: str, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    draft = _draft(data)
    if not draft.contact.name.strip():
        fail(409, "incomplete_profile", "The master profile has no name. Fix it on the Master Resume page and start a new session.")
    source, _view = render_latex(draft, data.config)
    folder = store.session_dir(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    _tex_path(store, session_id).write_text(source, encoding="utf-8")
    _pdf_path(store, session_id).unlink(missing_ok=True)  # an old PDF no longer matches the source
    data.generated = {"tex_sha256": sha256_text(source), "generated_at": now_iso(), "fingerprint": _fingerprint(data)}
    data.compile = data.validation = None
    return _save(store, meta, data)


@router.post("/sessions/{session_id}/compile")
def compile_pdf(session_id: str, request: Request) -> dict:
    store, meta, data = _load(request, session_id)
    tex_path = _tex_path(store, session_id)
    if not data.generated or not tex_path.is_file():
        fail(409, "no_source", "Generate the LaTeX source first.")
    if data.generated.get("fingerprint") != _fingerprint(data):
        fail(409, "stale_source", "The draft changed after the LaTeX was generated. Regenerate the source first.")
    source = tex_path.read_text("utf-8")
    current_sha = sha256_text(source)
    result = compile_latex(source, store.session_dir(session_id), timeout=settings_of(request).compile_timeout_seconds,
                           toolchain=detect_toolchain())
    data.compile = {"ok": result.ok, "engine": result.engine, "seconds": result.seconds, "error": result.error,
                    "log_excerpt": result.log_excerpt, "tex_sha256": result.tex_sha256, "compiled_at": now_iso()}
    data.validation = None
    log.info("compile session=%s ok=%s engine=%s seconds=%s", session_id, result.ok, result.engine, result.seconds)
    if result.ok and result.pdf_path:
        _source, view = render_latex(_draft(data), data.config)
        formatting = validate_pdf(result.pdf_path, view, data.config, compiled_sha=result.tex_sha256,
                                  current_sha=current_sha, engine=result.engine)
        qualification = qualification_report(
            master=data.profile, view=view, requirements=data.analysis.requirements if data.analysis else [],
            report=data.match, suggestions=data.suggestions)
        data.validation = {"formatting": formatting, "qualification": qualification}
    return _save(store, meta, data)


# ---------------------------------------------------------------- downloads


def _stem(meta: dict, data: SessionData) -> str:
    return f"{slug(data.profile.contact.name, 'resume')}-{slug(meta['job_title'] or data.config.target_role, 'tailored')}"


@router.get("/sessions/{session_id}/files/{kind}")
def download(session_id: str, kind: Literal["tex", "pdf", "report.md", "report.json"], request: Request,
             inline: bool = False):
    store, meta, data = _load(request, session_id)
    stem = _stem(meta, data)
    if kind == "tex":
        path = _tex_path(store, session_id)
        if not data.generated or not path.is_file():
            fail(404, "not_found", "No LaTeX source has been generated for this session.")
        return FileResponse(path, media_type="application/x-tex", filename=f"{stem}.tex")
    if kind == "pdf":
        path = _pdf_path(store, session_id)
        if not (data.compile and data.compile.get("ok")) or not path.is_file():
            fail(404, "not_found", "No PDF has been compiled for this session.")
        return FileResponse(path, media_type="application/pdf", filename=f"{stem}.pdf",
                            content_disposition_type="inline" if inline else "attachment")
    if kind == "report.md":
        body = render_match_report(resume_name=data.resume_name, resume_version=data.resume_version,
                                   created_at=meta["created_at"], analysis=data.analysis, report=data.match,
                                   suggestions=data.suggestions, validation=data.validation)
        return Response(body, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}-match-report.md"'})
    report = {
        "session": {**meta, "resume_name": data.resume_name, "resume_version": data.resume_version},
        "job_description": data.jd_text,
        "analysis": data.analysis.model_dump() if data.analysis else None,
        "match": data.match.model_dump() if data.match else None,
        "suggestions": [s.model_dump() for s in data.suggestions],
        "config": data.config.model_dump(),
        "generated": data.generated, "compile": data.compile, "validation": data.validation,
    }
    return Response(json.dumps(report, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{stem}-report.json"'})
