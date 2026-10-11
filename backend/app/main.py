"""FastAPI application factory."""
from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .ai.groq_client import GroqProvider
from .ai.provider import AIError, AIProvider
from .api import resumes, sessions, system
from .config import BACKEND_DIR, Settings, load_settings
from .storage.store import Store

log = logging.getLogger("cvforge")
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


def create_app(settings: Optional[Settings] = None, provider: Optional[AIProvider] = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="CV Forge", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.state.settings = settings
    app.state.store = Store(settings)
    app.state.provider = provider or GroqProvider(settings)
    app.state.store.purge_expired()

    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                           allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if (settings.access_token and path.startswith("/api/") and path != "/api/health"
                and request.method != "OPTIONS"):
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {settings.access_token}"
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                return JSONResponse({"detail": {"code": "unauthorized", "message": "A valid access token is required."}},
                                    status_code=401)
        response = await call_next(request)
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AIError)
    async def ai_error(_request: Request, exc: AIError):
        log.warning("ai error code=%s", exc.code)
        body = {"code": exc.code, "message": exc.message}
        if exc.retry_after is not None:
            body["retry_after"] = exc.retry_after
        return JSONResponse({"detail": body}, status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request: Request, exc: RequestValidationError):
        # Report where the problem is without echoing submitted (possibly personal) values.
        problems = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "problem": e.get("msg", "")}
                    for e in exc.errors()[:10]]
        first = problems[0] if problems else {"field": "", "problem": "invalid request"}
        return JSONResponse({"detail": {"code": "invalid_request", "problems": problems,
                                        "message": f"Invalid input for '{first['field']}': {first['problem']}"}},
                            status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    for module in (system, resumes, sessions):
        app.include_router(module.router, prefix="/api")

    if FRONTEND_DIST.is_dir():
        _mount_frontend(app, FRONTEND_DIST)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend from the same process (used for single-command/private hosting)."""
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found."})
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
