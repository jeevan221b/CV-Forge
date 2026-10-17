"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
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
                  redoc_url=None, lifespan=_idle_lifespan)
    app.state.settings = settings
    app.state.store = Store(settings)
    app.state.provider = provider or GroqProvider(settings)
    app.state.store.purge_expired()
    app.state.last_activity = time.monotonic()
    app.state.in_flight = 0

    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                           allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        # Everything but the health check counts as use. Mission Control polls /api/health, so it must not
        # keep an idle on-demand server alive; a long request (a PDF compile) does.
        counts = path != "/api/health"
        if counts:
            _touch(app, 1)
        try:
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
        finally:
            if counts:
                _touch(app, -1)

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


def _touch(app: FastAPI, delta: int) -> None:
    app.state.in_flight += delta
    app.state.last_activity = time.monotonic()


@asynccontextmanager
async def _idle_lifespan(app: FastAPI):
    minutes = app.state.settings.idle_shutdown_minutes
    task = asyncio.create_task(_idle_watch(app, minutes * 60)) if minutes > 0 else None
    if task:
        log.info("idle shutdown enabled after %d min without requests", minutes)
    yield
    if task:
        task.cancel()


async def _idle_watch(app: FastAPI, limit: float) -> None:
    while True:
        await asyncio.sleep(min(30.0, limit / 4))
        if app.state.in_flight == 0 and time.monotonic() - app.state.last_activity >= limit:
            log.info("no requests for %d s, shutting down", int(limit))
            # SIGTERM lets uvicorn finish its normal graceful shutdown.
            os.kill(os.getpid(), signal.SIGTERM)
            return


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
