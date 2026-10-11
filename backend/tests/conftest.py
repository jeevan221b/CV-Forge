"""Shared fixtures. Everything here uses fictional data and an isolated temp data directory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.latex.compiler import detect_toolchain
from app.main import create_app
from app.parsing.latex_parser import parse_latex

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
HAS_LATEX = detect_toolchain().can_compile
requires_latex = pytest.mark.skipif(not HAS_LATEX, reason="no LaTeX compiler installed (latexmk/pdflatex/xelatex/lualatex/tectonic)")


@pytest.fixture(scope="session")
def sample_tex() -> str:
    return (SAMPLES / "sample_resume.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sample_jd() -> str:
    return (SAMPLES / "sample_jd.txt").read_text(encoding="utf-8")


@pytest.fixture()
def profile(sample_tex):
    return parse_latex(sample_tex).profile


class FakeProvider:
    """Stands in for Groq. Returns whatever the test queued, or raises it."""

    name = "fake"
    model = "fake-model"

    def __init__(self, configured: bool = True):
        self.configured = configured
        self.queue: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return self.configured

    def complete_json(self, *, system: str, user: str, schema_name: str, json_schema: dict) -> dict:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if not self.queue:
            raise AssertionError("FakeProvider was called but nothing was queued")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(user) if callable(item) else item


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = dict(groq_api_key="", data_dir=tmp_path / "data", max_upload_bytes=200_000,
                                  compile_timeout_seconds=300)
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def client(tmp_path, provider) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path), provider=provider))


@pytest.fixture()
def resume(client, sample_tex) -> dict:
    r = client.post("/api/resumes", files={"file": ("sample_resume.tex", sample_tex.encode(), "application/x-tex")})
    assert r.status_code == 201, r.text
    return r.json()


def text_pdf(lines: list[str]) -> bytes:
    """A tiny hand-built PDF with real, extractable text (no LaTeX needed)."""
    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content = "BT /F1 11 Tf 72 740 Td 14 TL " + " ".join(f"({esc(ln)}) Tj T*" for ln in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
