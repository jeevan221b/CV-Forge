"""Plain-text resume parser, used for PDF imports and for LaTeX files without section commands.

Text extracted from a PDF has lost its structure, so everything here is a best guess and the
result always carries a warning asking the user to review it.
"""
from __future__ import annotations

import re
from typing import Optional

from . import heuristics as h
from .assemble import ParsedSection, ParseResult, assemble_profile

_HEADING_WORDS = set("""
professional summary profile objective about me work experience employment history career relevant education
academic background technical skills core competencies technologies tools projects personal selected side
certifications licenses certificates and awards honors honours publications languages interests volunteer
volunteering leadership activities additional information achievements references training courses research
key qualifications extracurricular open source contributions affiliations memberships hobbies other
""".split())
_BULLET_RE = re.compile(r"^(\s*)([•●▪■◦‣∙·*–➢►-])\s+(\S.*)$")


def _is_heading(line: str) -> bool:
    text = line.strip().rstrip(":")
    if not text or len(text) > 40 or text.endswith((".", ",")):
        return False
    words = [w for w in re.split(r"[\s&/]+", text.lower()) if w]
    if words and all(w in _HEADING_WORDS for w in words) and len(words) <= 4:
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    return (len(letters) >= 4 and text.upper() == text and len(words) <= 4
            and not re.search(r"\d|@", text) and not line.startswith("  "))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _section_events(lines: list[tuple[int, str]]) -> list[h.Event]:
    events: list[h.Event] = []
    bullet_indent: Optional[int] = None
    has_layout = any(_indent(text) > 0 for _, text in lines)
    for idx, (number, text) in enumerate(lines):
        if not text.strip():
            continue
        m = _BULLET_RE.match(text)
        if m:
            bullet_indent = len(m.group(1))
            events.append(h.Event(kind="item", text=m.group(3).strip(), line=number))
            continue
        last = events[-1] if events else None
        if last is not None and last.kind == "item" and bullet_indent is not None:
            next_text = next((t for _, t in lines[idx + 1:] if t.strip()), "")
            if has_layout:
                continuation = _indent(text) > bullet_indent
            else:
                continuation = (not h.DATE_RE.search(text) and not h.DATE_RE.search(next_text)
                                and not last.text.rstrip().endswith("."))
            if continuation:
                joiner = "" if last.text.endswith("-") and text.strip()[:1].islower() else " "
                last.text = (last.text[:-1] if joiner == "" else last.text) + joiner + text.strip()
                continue
        fields = "\t".join(p for p in re.split(r"\t| {3,}|\s+\|\s+(?=.*(?:19|20)\d{2})", text.strip()) if p)
        events.append(h.Event(kind="text", text=fields, line=number))
    return events


def parse_plain_text(text: str, urls: Optional[list[str]] = None) -> ParseResult:
    raw_lines = text.replace("\r\n", "\n").replace("\f", "\n").split("\n")
    numbered = list(enumerate(raw_lines, start=1))

    header: list[str] = []
    sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    for number, line in numbered:
        if _is_heading(line):
            sections.append((line.strip().rstrip(":"), number, []))
        elif sections:
            sections[-1][2].append((number, line))
        else:
            header.append(line)

    parsed: list[ParsedSection] = []
    for title, number, body in sections:
        key = h.classify_section(title)
        if key in ("summary", "skills"):
            # wrapped prose / lists: join lines that do not start a new "Category:" row
            merged: list[tuple[int, str]] = []
            for n, ln in body:
                stripped = ln.strip()
                if not stripped:
                    continue
                starts_row = key == "skills" and (re.match(r"^[^:,]{1,40}:", stripped) or _BULLET_RE.match(ln))
                if merged and not starts_row:
                    merged[-1] = (merged[-1][0], merged[-1][1] + " " + stripped)
                else:
                    merged.append((n, _BULLET_RE.sub(r"\3", ln).strip()))
            events = [h.Event(kind="text", text=t, line=n) for n, t in merged]
        else:
            events = _section_events(body)
        parsed.append(ParsedSection(title=title.title() if title.isupper() else title, events=events, line=number))

    profile, warnings = assemble_profile("\n".join(header), urls or [], parsed)
    warnings.insert(0, "This profile was inferred from plain text, where layout information is lost. "
                       "Check every employer, job title, date and bullet before saving.")
    return ParseResult(profile=profile, extracted_text=text.strip(), warnings=warnings)
