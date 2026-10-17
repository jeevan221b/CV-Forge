"""Health, preflight and settings endpoints."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import __version__
from ..ai.groq_client import SETUP_HINT
from ..latex.compiler import detect_toolchain
from ..storage.store import now_iso
from .deps import provider_of, settings_of, store_of

router = APIRouter()

PRIVACY_NOTICE = (
    "AI tailoring sends data to Groq, an external service. Each request contains the job requirements you "
    "extracted and the relevant parts of your resume: summary, skills, bullet points, and the job titles, "
    "employers, dates, education and certification headings they belong to. Your name, email, phone number, "
    "address and links are not sent. Everything else in CV Forge runs locally on this machine. Groq's own "
    "data-handling terms apply to what is sent."
)


@router.get("/health")
def health(request: Request) -> dict:
    body: dict = {"status": "ok", "version": __version__}
    minutes = settings_of(request).idle_shutdown_minutes
    if minutes:
        # For Mission Control's status panel: how long until this on-demand server stops itself.
        idle = time.monotonic() - request.app.state.last_activity
        body["idle_shutdown"] = {"after_minutes": minutes, "idle_seconds": round(idle),
                                 "remaining_seconds": max(0, round(minutes * 60 - idle))}
    return body


@router.post("/keepalive")
def keepalive() -> dict:
    """Sent by the UI while someone is working, so an idle-shutdown server (CVFORGE_IDLE_SHUTDOWN_MINUTES)
    does not stop under a long edit that makes no other request. The request itself is the signal."""
    return {"ok": True}


@router.get("/system")
def system(request: Request) -> dict:
    s, store, provider = settings_of(request), store_of(request), provider_of(request)
    prefs = store.get_settings()
    return {
        "version": __version__,
        "ai": {
            "provider": provider.name,
            "model": provider.model,
            "configured": provider.is_configured(),
            "structured_output": "json_schema (strict)" if s.use_strict_schema else "json_object + local validation",
            "setup_hint": "" if provider.is_configured() else SETUP_HINT,
            "consent": bool(prefs["ai_consent"]),
            "consent_at": prefs["ai_consent_at"],
            "privacy_notice": PRIVACY_NOTICE,
        },
        "toolchain": detect_toolchain().to_dict(),
        "limits": {"max_upload_mb": s.max_upload_bytes // (1024 * 1024), "compile_timeout_seconds": s.compile_timeout_seconds},
        "server": {"host": s.host, "port": s.port, "local_only": s.host in ("127.0.0.1", "localhost", "::1"),
                   "access_token_required": bool(s.access_token), "data_dir": str(s.data_dir)},
        "retention_days": prefs["retention_days"],
        "counts": store.counts(),
    }


class SettingsUpdate(BaseModel):
    ai_consent: Optional[bool] = None
    retention_days: Optional[int] = Field(default=None, ge=0, le=3650)


@router.put("/settings")
def update_settings(body: SettingsUpdate, request: Request) -> dict:
    store = store_of(request)
    values: dict = {}
    if body.ai_consent is not None:
        values["ai_consent"] = body.ai_consent
        values["ai_consent_at"] = now_iso() if body.ai_consent else None
    if body.retention_days is not None:
        values["retention_days"] = body.retention_days
    prefs = store.set_settings(values)
    purged = store.purge_expired() if body.retention_days else 0
    return {**prefs, "purged_sessions": purged}


@router.post("/settings/purge")
def purge(request: Request) -> dict:
    return {"purged_sessions": store_of(request).purge_expired()}
