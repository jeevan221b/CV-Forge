"""Shared request helpers."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, NoReturn

from fastapi import HTTPException, Request

from ..ai.provider import AIProvider
from ..config import Settings
from ..storage.store import InvalidId, Store


def fail(status: int, code: str, message: str, **extra: Any) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def store_of(request: Request) -> Store:
    return request.app.state.store


def provider_of(request: Request) -> AIProvider:
    return request.app.state.provider


def check_id(store: Store, kind: str, ident: str) -> None:
    try:
        store.resume_dir(ident) if kind == "resume" else store.session_dir(ident)
    except InvalidId:
        fail(404, "not_found", f"{kind.capitalize()} not found.")


def clean_name(value: str, fallback: str = "Untitled", limit: int = 80) -> str:
    """Display name: printable, single-line, bounded. Never used as a path."""
    value = "".join(ch for ch in unicodedata.normalize("NFC", value or "") if ch.isprintable())
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or fallback


def slug(value: str, fallback: str = "resume") -> str:
    """ASCII-only token for download file names."""
    ascii_ = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    out = re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-").lower()
    return out[:40] or fallback
