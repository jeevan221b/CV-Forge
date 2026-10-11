"""Persistence: SQLite for metadata and history, the filesystem for documents.

Layout under the data directory:
    cvforge.sqlite3
    uploads/<resume_id>/original.tex|pdf     written once at upload, never modified
    sessions/<session_id>/resume.tex|pdf     generated per tailoring session
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, Field

from ..config import Settings
from ..models import JDAnalysis, MatchReport, ResumeConfig, ResumeProfile, Suggestion

_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, source_filename TEXT NOT NULL, source_kind TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1, verified INTEGER NOT NULL DEFAULT 0,
    extracted_text TEXT NOT NULL DEFAULT '', warnings TEXT NOT NULL DEFAULT '[]', profile TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, resume_id TEXT, job_title TEXT NOT NULL DEFAULT '', employer TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft', data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
DEFAULT_SETTINGS: dict[str, Any] = {"ai_consent": False, "ai_consent_at": None, "retention_days": 0}


class InvalidId(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_uuid() -> str:
    return uuid.uuid4().hex


class SessionData(BaseModel):
    """Everything a tailoring session owns. `profile` is a private snapshot of the master resume
    taken when the session was created, so sessions cannot affect each other or the master."""

    resume_name: str = ""
    resume_version: int = 1
    profile: ResumeProfile = Field(default_factory=ResumeProfile)
    jd_text: str = ""
    analysis: Optional[JDAnalysis] = None
    match: Optional[MatchReport] = None
    suggestions: list[Suggestion] = Field(default_factory=list)
    ai_meta: dict[str, Any] = Field(default_factory=dict)
    config: ResumeConfig = Field(default_factory=ResumeConfig)
    generated: Optional[dict[str, Any]] = None
    compile: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        for d in (self.root, settings.uploads_dir, settings.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.settings.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---------------------------------------------------------------- safe paths

    def _dir(self, base: Path, ident: str) -> Path:
        """Directory for an ID. IDs are server-generated hex; anything else is refused, and the
        resolved path must stay inside the data directory."""
        if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
            raise InvalidId("Invalid identifier.")
        path = (base / ident).resolve()
        if not path.is_relative_to(base.resolve()):
            raise InvalidId("Invalid identifier.")
        return path

    def resume_dir(self, resume_id: str) -> Path:
        return self._dir(self.settings.uploads_dir, resume_id)

    def session_dir(self, session_id: str) -> Path:
        return self._dir(self.settings.sessions_dir, session_id)

    # ---------------------------------------------------------------- settings

    def get_settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        with self._db() as db:
            for row in db.execute("SELECT key, value FROM settings"):
                if row["key"] in out:
                    out[row["key"]] = json.loads(row["value"])
        return out

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._db() as db:
            for key, value in values.items():
                if key in DEFAULT_SETTINGS:
                    db.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
        return self.get_settings()

    # ---------------------------------------------------------------- resumes

    @staticmethod
    def _resume(row: sqlite3.Row, full: bool = True) -> dict[str, Any]:
        out = {k: row[k] for k in ("id", "name", "source_filename", "source_kind", "version", "created_at", "updated_at")}
        out["verified"] = bool(row["verified"])
        if full:
            out["extracted_text"] = row["extracted_text"]
            out["warnings"] = json.loads(row["warnings"])
            out["profile"] = json.loads(row["profile"])
        return out

    def create_resume(self, *, name: str, source_filename: str, source_kind: str, original: Optional[bytes],
                      extracted_text: str, warnings: list[str], profile: ResumeProfile,
                      resume_id: Optional[str] = None) -> dict[str, Any]:
        resume_id = resume_id or new_uuid()
        if original is not None:
            self.write_original(resume_id, source_kind, original)
        ts = now_iso()
        with self._db() as db:
            db.execute(
                "INSERT INTO resumes(id, name, source_filename, source_kind, extracted_text, warnings, profile, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (resume_id, name, source_filename, source_kind, extracted_text, json.dumps(warnings),
                 profile.model_dump_json(), ts, ts))
        return self.get_resume(resume_id)  # type: ignore[return-value]

    def write_original(self, resume_id: str, source_kind: str, original: bytes) -> Path:
        """Store the upload byte-for-byte. Refuses to replace an existing original."""
        folder = self.resume_dir(resume_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"original.{'pdf' if source_kind == 'pdf' else 'tex'}"
        with open(path, "xb") as fh:  # 'x': fail rather than overwrite
            fh.write(original)
        os.chmod(path, 0o400)
        return path

    def original_path(self, resume_id: str) -> Optional[Path]:
        folder = self.resume_dir(resume_id)
        for name in ("original.tex", "original.pdf"):
            if (folder / name).is_file():
                return folder / name
        return None

    def list_resumes(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM resumes ORDER BY updated_at DESC").fetchall()
        return [self._resume(r, full=False) for r in rows]

    def get_resume(self, resume_id: str) -> Optional[dict[str, Any]]:
        with self._db() as db:
            row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        return self._resume(row) if row else None

    def update_resume(self, resume_id: str, *, profile: ResumeProfile, name: Optional[str], verified: bool) -> Optional[dict[str, Any]]:
        with self._db() as db:
            cur = db.execute(
                "UPDATE resumes SET profile = ?, name = COALESCE(?, name), verified = ?, version = version + 1, "
                "updated_at = ? WHERE id = ?",
                (profile.model_dump_json(), name, int(verified), now_iso(), resume_id))
        return self.get_resume(resume_id) if cur.rowcount else None

    def delete_resume(self, resume_id: str) -> bool:
        folder = self.resume_dir(resume_id)
        with self._db() as db:
            cur = db.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
        if folder.exists():
            for p in folder.iterdir():
                try:
                    os.chmod(p, 0o600)
                except OSError:
                    pass
            shutil.rmtree(folder, ignore_errors=True)
        return bool(cur.rowcount)

    # ---------------------------------------------------------------- sessions

    @staticmethod
    def _status(data: SessionData) -> str:
        if data.compile and data.compile.get("ok"):
            return "compiled"
        if data.generated:
            return "generated"
        if data.suggestions:
            return "tailoring"
        if data.analysis:
            return "analyzed"
        return "draft"

    def create_session(self, resume: dict[str, Any]) -> str:
        """Start from the master profile as it is right now. Nothing is copied from other sessions."""
        session_id = new_uuid()
        data = SessionData(resume_name=resume["name"], resume_version=resume["version"],
                           profile=ResumeProfile.model_validate(resume["profile"]))
        ts = now_iso()
        with self._db() as db:
            db.execute("INSERT INTO sessions(id, resume_id, data, created_at, updated_at) VALUES(?,?,?,?,?)",
                       (session_id, resume["id"], data.model_dump_json(), ts, ts))
        return session_id

    def get_session(self, session_id: str) -> Optional[tuple[dict[str, Any], SessionData]]:
        with self._db() as db:
            row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        meta = {k: row[k] for k in ("id", "resume_id", "job_title", "employer", "status", "created_at", "updated_at")}
        return meta, SessionData.model_validate_json(row["data"])

    def save_session(self, session_id: str, data: SessionData, *, job_title: Optional[str] = None,
                     employer: Optional[str] = None) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE sessions SET data = ?, status = ?, job_title = COALESCE(?, job_title), "
                "employer = COALESCE(?, employer), updated_at = ? WHERE id = ?",
                (data.model_dump_json(), self._status(data), job_title, employer, now_iso(), session_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT s.id, s.resume_id, s.job_title, s.employer, s.status, s.created_at, s.updated_at, "
                "json_extract(s.data, '$.resume_name') AS resume_name, "
                "json_extract(s.data, '$.resume_version') AS resume_version, "
                "json_extract(s.data, '$.match.score.value') AS match_score "
                "FROM sessions s ORDER BY s.updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        folder = self.session_dir(session_id)
        with self._db() as db:
            cur = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        shutil.rmtree(folder, ignore_errors=True)
        return bool(cur.rowcount)

    def purge_expired(self, retention_days: Optional[int] = None) -> int:
        """Delete tailoring sessions (and their generated files) older than the retention period.
        Master resumes are never purged automatically. 0 disables purging."""
        days = self.get_settings()["retention_days"] if retention_days is None else retention_days
        if not days or days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat(timespec="seconds")
        with self._db() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM sessions WHERE updated_at < ?", (cutoff,))]
        for session_id in ids:
            self.delete_session(session_id)
        return len(ids)

    def counts(self) -> dict[str, int]:
        with self._db() as db:
            resumes = db.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
            sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            drafts = db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('generated', 'compiled')").fetchone()[0]
        return {"resumes": resumes, "sessions": sessions, "generated_drafts": drafts}
