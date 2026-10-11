"""Deterministic checks of the compiled PDF against the approved draft, plus the ATS report.

Formatting quality (can a parser read this document?) and qualification match (does the
candidate's documented experience fit the job?) are reported separately. Neither is a
prediction of how any particular applicant tracking system will behave.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..lexicon import term_in_text
from ..models import MatchReport, Requirement, ResumeConfig, ResumeProfile, Suggestion, profile_corpus
from ..parsing.pdf_extract import PdfExtractionError, extract_pdf_text
from ..latex.renderer import ResumeView, display_url

DISCLAIMER = ("These are deterministic checks of this document. They cannot guarantee compatibility with every "
              "applicant tracking system, and nothing here predicts interview or hiring outcomes.")
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_DATE_STYLES = [
    ("Mon YYYY", re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.? (?:19|20)\d{2}\b")),
    ("Month YYYY", re.compile(r"\b(?:January|February|March|April|June|July|August|September|October|November|"
                              r"December) (?:19|20)\d{2}\b")),
    ("MM/YYYY", re.compile(r"\b\d{1,2}/(?:19|20)\d{2}\b")),
]


def squash(text: str) -> str:
    """Letters and digits only, lower-case. Makes comparisons immune to line wrapping, hyphenation,
    ligatures and quote/dash styles while still catching changed words and numbers."""
    text = unicodedata.normalize("NFKC", text)
    for lig, plain in _LIGATURES.items():
        text = text.replace(lig, plain)
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _check(cid: str, category: str, label: str, status: str, detail: str = "", items: Optional[list[str]] = None) -> dict:
    return {"id": cid, "category": category, "label": label, "status": status, "detail": detail, "items": items or []}


def _presence(cid: str, category: str, label: str, expected: list[str], haystack: str, fail_status: str = "fail") -> dict:
    expected = [e for e in dict.fromkeys(expected) if e and squash(e)]
    if not expected:
        return _check(cid, category, label, "info", "Nothing to check — the draft has none.")
    missing = [e for e in expected if squash(e) not in haystack]
    if missing:
        return _check(cid, category, label, fail_status,
                      f"{len(missing)} of {len(expected)} not found in the text extracted from the PDF.", missing)
    return _check(cid, category, label, "pass", f"All {len(expected)} found in the extracted text.")


def date_consistency(view: ResumeView) -> dict:
    dates = [(e.heading, e.dates) for s in view.sections if s.key in ("experience", "education") for e in s.entries]
    missing = [h for h, d in dates if s_blank(d)]
    styles: dict[str, list[str]] = {}
    for _, d in dates:
        for name, pat in _DATE_STYLES:
            if pat.search(d):
                styles.setdefault(name, []).append(d)
                break
        else:
            if re.search(r"(?:19|20)\d{2}", d):
                styles.setdefault("YYYY", []).append(d)
    problems: list[str] = [f"No dates: {h}" for h in missing]
    month_styles = [k for k in styles if k != "YYYY"]
    if len(month_styles) > 1:
        problems.append("Mixed date formats: " + "; ".join(f"{k} (e.g. {v[0]})" for k, v in styles.items() if k != "YYYY"))
    if problems:
        return _check("date_consistency", "Date consistency", "Dates are present and use one format", "warn",
                      "Inconsistent or missing dates make timelines harder to parse.", problems)
    return _check("date_consistency", "Date consistency", "Dates are present and use one format", "pass",
                  f"{len(dates)} dated entries use a consistent format." if dates else "No dated entries.")


def s_blank(value: str) -> bool:
    return not value or not value.strip()


def validate_pdf(pdf_path: Path, view: ResumeView, config: ResumeConfig, *, compiled_sha: str,
                 current_sha: str, engine: Optional[str]) -> dict[str, Any]:
    """Formatting/readability checks. Returns {'checks': [...], 'extracted_text': str, 'pages': int, ...}."""
    checks: list[dict] = []
    base = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine": engine,
            "tex_sha256": current_sha, "disclaimer": DISCLAIMER}

    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        checks.append(_check("pdf_exists", "Document readability", "PDF file exists and is readable", "fail",
                             "No PDF is available for this draft. Compile the source first."))
        return {**base, "checks": checks, "extracted_text": "", "pages": 0, "ok": False}
    try:
        extracted = extract_pdf_text(pdf_path, layout=False)
    except PdfExtractionError as exc:
        checks.append(_check("pdf_exists", "Document readability", "PDF file exists and is readable", "fail", str(exc)))
        return {**base, "checks": checks, "extracted_text": "", "pages": 0, "ok": False}

    text, pages = extracted.text, extracted.pages
    hay = squash(text)
    checks.append(_check("pdf_exists", "Document readability", "PDF file exists and is readable", "pass",
                         f"{pdf_path.stat().st_size // 1024 or 1} KB, {pages} page(s), text extracted with {extracted.method}."))
    checks.append(_check(
        "source_match", "Document readability", "PDF was built from the current .tex source",
        "pass" if compiled_sha == current_sha else "fail",
        "The PDF's recorded source hash matches the stored .tex." if compiled_sha == current_sha
        else "The stored .tex differs from the source this PDF was compiled from. Recompile."))
    if pages > config.max_pages:
        checks.append(_check("page_count", "Document readability", f"Fits the page limit ({config.max_pages})", "warn",
                             f"The PDF has {pages} pages. Content was not cut to fit — shorten it, lower the font "
                             "size, or raise the limit if the extra length is justified."))
    else:
        checks.append(_check("page_count", "Document readability", f"Fits the page limit ({config.max_pages})", "pass",
                             f"{pages} page(s)."))

    visible = len("".join(text.split()))
    garbled = "�" in text or "(cid:" in text
    if visible < 200:
        checks.append(_check("text_extraction", "Text extraction", "Text can be extracted", "fail",
                             f"Only {visible} characters were extracted."))
    elif garbled:
        checks.append(_check("text_extraction", "Text extraction", "Text can be extracted", "warn",
                             "Extracted text contains unmapped glyphs; some characters may not be machine-readable."))
    else:
        checks.append(_check("text_extraction", "Text extraction", "Text can be extracted", "pass",
                             f"{visible} characters of selectable text."))
    for w in extracted.warnings:
        checks.append(_check("extractor_note", "Text extraction", "Extractor note", "info", w))

    headings = [s.heading for s in view.sections]
    checks.append(_presence("headings", "Section headings", "Expected section headings appear", headings, hay))
    unconventional = [h for h in headings if h not in ("Summary", "Skills", "Experience", "Projects", "Education",
                                                       "Certifications")]
    if unconventional:
        checks.append(_check("heading_names", "Section headings", "Headings use conventional names", "info",
                             "Custom section titles are kept as written; parsers recognise standard names most reliably.",
                             unconventional))

    contact = [view.name, *view.contact_items, *(display_url(u) for u in view.links)]
    checks.append(_presence("contact", "Contact information", "Contact details are preserved in the body text",
                            contact, hay))
    if not view.email:
        checks.append(_check("contact_email", "Contact information", "Email address present", "warn",
                             "The draft has no email address."))

    exp = [e for s in view.sections if s.key == "experience" for e in s.entries]
    edu = [e for s in view.sections if s.key == "education" for e in s.entries]
    prj = [e for s in view.sections if s.key == "projects" for e in s.entries]
    checks.append(_presence("employment", "Protected facts", "Job titles, employers and locations are preserved",
                            [x for e in exp for x in (e.heading, e.subheading)], hay))
    checks.append(_presence("employment_dates", "Protected facts", "Employment and education dates are preserved",
                            [e.dates for e in [*exp, *edu]], hay))
    checks.append(_presence("education", "Protected facts", "Institutions and degrees are preserved",
                            [x for e in edu for x in (e.heading, e.subheading)], hay))
    checks.append(_presence("projects", "Protected facts", "Project names are preserved", [e.heading for e in prj], hay))
    certs = [line for s in view.sections if s.key == "certifications" for line in s.lines]
    if certs:
        checks.append(_presence("certifications", "Protected facts", "Certifications are preserved", certs, hay))

    checks.append(_presence("approved_content", "Approved content", "Every approved line appears in the PDF",
                            view.all_text(), hay))

    # Reverse direction: is there anything in the PDF that the approved draft does not contain?
    allowed = squash(" ".join(view.all_text()))
    stray = []
    for token in re.findall(r"[^\W_]{3,}", unicodedata.normalize("NFKC", text)):
        if squash(token) not in allowed and token not in stray:
            stray.append(token)
    if stray:
        checks.append(_check("unapproved_content", "Approved content", "No text beyond the approved draft", "warn",
                             "Words were extracted that are not in the approved draft. This is usually a line-break "
                             "hyphenation artefact, but check that nothing unintended was added.", stray[:25]))
    else:
        checks.append(_check("unapproved_content", "Approved content", "No text beyond the approved draft", "pass",
                             "Every extracted word comes from the approved draft."))

    # Reading order: name first, then sections and entries in the configured order.
    sequence = [view.name, *[x for s in view.sections for x in (s.heading, *(e.heading for e in s.entries))]]
    cursor, out_of_order = 0, []
    for label in sequence:
        key = squash(label)
        if not key:
            continue
        pos = hay.find(key, cursor)
        if pos < 0:
            if hay.find(key) >= 0:
                out_of_order.append(label)
            continue
        cursor = pos + len(key)
    if out_of_order:
        checks.append(_check("reading_order", "Reading order", "Extracted text follows the intended order", "warn",
                             "These items appear earlier in the extracted text than intended.", out_of_order))
    else:
        checks.append(_check("reading_order", "Reading order", "Extracted text follows the intended order", "pass",
                             "Name, sections and entries are extracted in document order."))

    checks.append(date_consistency(view))

    concerns: list[str] = []
    long_bullets = [b for s in view.sections for e in s.entries for b in e.bullets if len(b) > 300]
    if long_bullets:
        concerns.append(f"{len(long_bullets)} bullet(s) exceed 300 characters and may be hard to scan.")
    crowded = [e.heading for s in view.sections for e in s.entries if len(e.bullets) > 8]
    if crowded:
        concerns.append("More than 8 bullets under: " + ", ".join(crowded))
    if not any(s.key == "experience" for s in view.sections):
        concerns.append("There is no Experience section.")
    if not any(s.key == "education" for s in view.sections):
        concerns.append("There is no Education section.")
    checks.append(_check("formatting", "Formatting concerns", "Layout is single-column with standard bullets",
                         "warn" if concerns else "pass",
                         "The template uses one column, no tables, graphics or icons, and standard bullet points."
                         + (" Content-related concerns are listed below." if concerns else ""), concerns))

    ok = not any(c["status"] == "fail" for c in checks)
    return {**base, "checks": checks, "extracted_text": text.strip(), "pages": pages, "ok": ok,
            "summary": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail", "info")}}


def qualification_report(*, master: ResumeProfile, view: ResumeView, requirements: list[Requirement],
                         report: Optional[MatchReport], suggestions: list[Suggestion]) -> dict[str, Any]:
    """Qualification side of the ATS report: what the documented experience does and does not cover."""
    by_id = {r.id: r for r in requirements}
    matches = report.matches if report else []
    status = {m.requirement_id: m.status for m in matches}
    corpus = profile_corpus(master)
    draft_text = "\n".join(view.all_text())

    required = [r for r in requirements if r.importance == "must" and r.category != "terminology"]
    gaps = [{"id": m.requirement_id, "text": by_id[m.requirement_id].text,
             "importance": by_id[m.requirement_id].importance, "missing_terms": m.missing_terms}
            for m in matches if m.status == "unsupported" and m.requirement_id in by_id
            and by_id[m.requirement_id].category != "terminology"]
    unconfirmed = [{"id": m.requirement_id, "text": by_id[m.requirement_id].text, "note": m.note}
                   for m in matches if m.status in ("needs_confirmation", "indirect") and m.requirement_id in by_id]

    keywords = list(dict.fromkeys(k for r in requirements for k in r.keywords))
    documented = [k for k in keywords if term_in_text(k, corpus)]
    terminology = {
        "present": [k for k in documented if term_in_text(k, draft_text)],
        "documented_but_not_in_this_draft": [k for k in documented if not term_in_text(k, draft_text)],
        "not_documented": [k for k in keywords if k not in documented],
    }
    confirmed = [{"id": s.id, "target": s.target_label, "text": s.applied_text or "",
                  "flags": [f.model_dump() for f in s.flags if f.severity != "info"]}
                 for s in suggestions
                 if s.status in ("accepted", "modified") and s.requires_confirmation and s.confirmed]
    return {
        "score": report.score.model_dump() if report else None,
        "required_total": len(required),
        "required_supported": sum(1 for r in required if status.get(r.id) == "supported"),
        "gaps": gaps,
        "needs_confirmation": unconfirmed,
        "terminology": terminology,
        "user_confirmed_claims": confirmed,
        "note": "Gaps are reported as gaps. CV Forge does not add unsupported requirements to the resume.",
    }
