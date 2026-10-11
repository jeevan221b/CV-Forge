"""Master resume import and profile management."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..models import ResumeProfile, Traced, profile_issues
from ..parsing.latex_parser import parse_latex
from ..parsing.pdf_extract import PdfExtractionError, extract_pdf_text
from ..parsing.text_parser import parse_plain_text
from ..storage.store import new_uuid
from .deps import check_id, clean_name, fail, settings_of, slug, store_of

router = APIRouter()
log = logging.getLogger("cvforge.resumes")

ALLOWED = {".tex": "tex", ".pdf": "pdf"}


def _with_issues(resume: dict) -> dict:
    resume["issues"] = profile_issues(ResumeProfile.model_validate(resume["profile"]))
    return resume


def decode_tex(raw: bytes) -> tuple[str, list[str]]:
    if b"\x00" in raw:
        fail(415, "invalid_file", "This does not look like a LaTeX text file.")
    try:
        return raw.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return raw.decode("latin-1"), ["The file is not UTF-8; it was read as Latin-1. Check accented characters."]


@router.get("/resumes")
def list_resumes(request: Request) -> list[dict]:
    return store_of(request).list_resumes()


@router.post("/resumes", status_code=201)
async def upload_resume(request: Request, file: UploadFile = File(...), name: str = Form("")) -> dict:
    s, store = settings_of(request), store_of(request)
    filename = Path(file.filename or "").name  # drop any client-supplied directory components
    kind = ALLOWED.get(Path(filename).suffix.lower())
    if not kind:
        fail(415, "unsupported_type", "Only .tex and .pdf files can be imported.")
    raw = await file.read(s.max_upload_bytes + 1)
    if len(raw) > s.max_upload_bytes:
        fail(413, "too_large", f"The file is larger than the {s.max_upload_bytes // (1024 * 1024)} MB upload limit.")
    if not raw.strip():
        fail(400, "empty_file", "The uploaded file is empty.")

    resume_id = new_uuid()
    display = clean_name(name or Path(filename).stem, "Master resume")
    if kind == "pdf":
        if not raw.lstrip()[:5] == b"%PDF-":
            fail(415, "invalid_file", "The file has a .pdf extension but is not a PDF.")
        path = store.write_original(resume_id, "pdf", raw)
        try:
            extracted = extract_pdf_text(path, layout=True)
        except PdfExtractionError as exc:
            store.delete_resume(resume_id)
            fail(422, "unreadable_pdf", str(exc))
        result = parse_plain_text(extracted.text)
        result.warnings = extracted.warnings + result.warnings
        original = None
    else:
        text, notes = decode_tex(raw)
        result = parse_latex(text)
        result.warnings = notes + result.warnings
        original = raw
    log.info("resume imported id=%s kind=%s bytes=%s warnings=%s", resume_id, kind, len(raw), len(result.warnings))
    return _with_issues(store.create_resume(
        name=display, source_filename=clean_name(filename, "upload"), source_kind=kind, original=original,
        extracted_text=result.extracted_text, warnings=result.warnings, profile=result.profile, resume_id=resume_id))


class ManualResume(BaseModel):
    name: str = "Master resume"


@router.post("/resumes/manual", status_code=201)
def create_manual(body: ManualResume, request: Request) -> dict:
    """Start an empty profile to fill in by hand (no source document)."""
    return _with_issues(store_of(request).create_resume(
        name=clean_name(body.name, "Master resume"), source_filename="(entered manually)", source_kind="manual",
        original=None, extracted_text="", warnings=["This profile has no source document; every field is user-entered."],
        profile=ResumeProfile()))


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: str, request: Request) -> dict:
    store = store_of(request)
    check_id(store, "resume", resume_id)
    resume = store.get_resume(resume_id)
    if not resume:
        fail(404, "not_found", "Resume not found.")
    return _with_issues(resume)


class ProfileUpdate(BaseModel):
    profile: ResumeProfile
    name: Optional[str] = None
    verified: bool = False


def mark_user_edits(old: ResumeProfile, new: ResumeProfile, verified: bool) -> None:
    """Anything the user added or changed is recorded as user-provided rather than document-derived."""
    def index(profile: ResumeProfile) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for key in ("skills", "experience", "projects", "education", "certifications", "other"):
            for entry in getattr(profile, key):
                out[entry.id] = entry.model_dump(exclude={"bullets", "details", "origin", "source_line", "uncertain"}
                                                 | ({"items"} if key == "other" else set()))
                for attr in ("bullets", "details", "items"):
                    for child in getattr(entry, attr, []) or []:
                        if isinstance(child, Traced):
                            out[child.id] = child.model_dump(exclude={"origin", "source_line", "uncertain"})
        return out

    before = index(old)
    for key in ("skills", "experience", "projects", "education", "certifications", "other"):
        for entry in getattr(new, key):
            items = [entry] + [c for attr in ("bullets", "details", "items")
                               for c in (getattr(entry, attr, []) or []) if isinstance(c, Traced)]
            for obj in items:
                current = index_one(obj, key if obj is entry else "")
                if before.get(obj.id) != current:
                    obj.origin, obj.source_line, obj.uncertain = "user", None, False
                elif verified:
                    obj.uncertain = False
    if new.summary.strip() != old.summary.strip():
        new.summary_origin = "user"


def index_one(obj: Traced, key: str) -> dict:
    exclude = {"origin", "source_line", "uncertain"}
    if key:
        exclude |= {"bullets", "details"} | ({"items"} if key == "other" else set())
    return obj.model_dump(exclude=exclude)


@router.put("/resumes/{resume_id}")
def update_resume(resume_id: str, body: ProfileUpdate, request: Request) -> dict:
    store = store_of(request)
    check_id(store, "resume", resume_id)
    existing = store.get_resume(resume_id)
    if not existing:
        fail(404, "not_found", "Resume not found.")
    mark_user_edits(ResumeProfile.model_validate(existing["profile"]), body.profile, body.verified)
    name = clean_name(body.name, existing["name"]) if body.name is not None else None
    updated = store.update_resume(resume_id, profile=body.profile, name=name, verified=body.verified)
    return _with_issues(updated)  # type: ignore[arg-type]


@router.delete("/resumes/{resume_id}")
def delete_resume(resume_id: str, request: Request) -> dict:
    store = store_of(request)
    check_id(store, "resume", resume_id)
    if not store.delete_resume(resume_id):
        fail(404, "not_found", "Resume not found.")
    return {"deleted": True}


@router.get("/resumes/{resume_id}/original")
def download_original(resume_id: str, request: Request) -> FileResponse:
    store = store_of(request)
    check_id(store, "resume", resume_id)
    resume = store.get_resume(resume_id)
    path = store.original_path(resume_id) if resume else None
    if not resume or not path:
        fail(404, "not_found", "No original document is stored for this resume.")
    ext = path.suffix
    return FileResponse(path, media_type="application/pdf" if ext == ".pdf" else "application/x-tex",
                        filename=f"{slug(resume['name'])}-original{ext}")
