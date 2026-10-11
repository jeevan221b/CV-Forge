"""PDF text extraction: `pdftotext` (Poppler) when installed, pure-Python `pypdf` otherwise."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MIN_CHARS_PER_PAGE = 120


class PdfExtractionError(Exception):
    pass


@dataclass
class PdfText:
    text: str
    pages: int
    method: str
    warnings: list[str] = field(default_factory=list)


def pdftotext_path() -> Optional[str]:
    return shutil.which("pdftotext")


def page_count(path: Path) -> int:
    try:
        return len(PdfReader(str(path)).pages)
    except (PdfReadError, OSError, ValueError, KeyError) as exc:
        raise PdfExtractionError("The file could not be read as a PDF.") from exc


def _with_pdftotext(path: Path, layout: bool) -> Optional[str]:
    exe = pdftotext_path()
    if not exe:
        return None
    args = [exe, "-enc", "UTF-8"] + (["-layout"] if layout else []) + [str(path), "-"]
    try:
        done = subprocess.run(args, capture_output=True, timeout=30, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def _with_pypdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many unrelated error types on malformed files
        raise PdfExtractionError("Text could not be extracted from this PDF.") from exc


def extract_pdf_text(path: Path, layout: bool = True) -> PdfText:
    pages = page_count(path)
    text = _with_pdftotext(path, layout)
    method = "pdftotext"
    if text is None:
        text = _with_pypdf(path)
        method = "pypdf"
    warnings: list[str] = []
    visible = len("".join(text.split()))
    if pages == 0:
        warnings.append("The PDF has no pages.")
    elif visible == 0:
        warnings.append("No text could be extracted. This PDF is probably a scan or image; "
                        "import the .tex source instead or enter the profile manually.")
    elif visible / pages < MIN_CHARS_PER_PAGE:
        warnings.append(f"Very little text was extracted ({visible} characters over {pages} page(s)). "
                        "The PDF may be scanned or use fonts without a text layer, so parsing is unreliable.")
    if method == "pypdf":
        warnings.append("pdftotext is not installed; used the built-in extractor, which preserves less layout.")
    return PdfText(text=text, pages=pages, method=method, warnings=warnings)
