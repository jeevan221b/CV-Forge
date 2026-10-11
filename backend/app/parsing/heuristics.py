"""Format-independent resume heuristics shared by the LaTeX and plain-text parsers.

Both parsers reduce a section to a list of `Event`s (entry headings, bullet items, loose text
lines); this module turns those into profile objects. Whenever a field assignment is a guess
the object is marked `uncertain` so the UI can ask the user to verify it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models import (
    Bullet, Certification, Contact, Education, Experience, OtherSection, Project, SkillGroup, new_id,
)


@dataclass
class Event:
    kind: str  # "entry" | "item" | "text"
    fields: list[str] = field(default_factory=list)  # entry: heading fields
    text: str = ""  # item / text: plain text (text may contain newlines and tabs)
    line: Optional[int] = None
    depth: int = 0
    urls: list[str] = field(default_factory=list)
    long_fields: list[str] = field(default_factory=list)  # entry args that read like descriptions
    macro: str = ""


@dataclass
class RawEntry:
    fields: list[str]
    bullets: list[tuple[str, Optional[int]]]
    line: Optional[int]
    urls: list[str]


# ---------------------------------------------------------------- section titles

_SECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("education", re.compile(r"educat|academic", re.I)),
    ("certifications", re.compile(r"certif|licen[sc]", re.I)),
    ("skills", re.compile(r"skill|technolog|competenc|proficienc|tech stack|toolbox", re.I)),
    ("projects", re.compile(r"project", re.I)),
    ("summary", re.compile(r"summary|profile|objective|about", re.I)),
    ("experience", re.compile(r"experience|employment|work|career|internship|professional background", re.I)),
]


def classify_section(title: str) -> str:
    for key, pat in _SECTION_RULES:
        if pat.search(title):
            return key
    return "other"


# ---------------------------------------------------------------- field patterns

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Fall|Autumn|Winter)\.?")
_POINT = rf"(?:(?:{_MONTH}\s+)?(?:19|20)\d{{2}}|\d{{1,2}}/(?:19|20)\d{{2}})"
_END = rf"(?:{_POINT}|Present|Current|Now|Ongoing|Today)"
DATE_RE = re.compile(
    rf"(?:Expected\s+|Graduat\w+\s+)?(?:{_POINT}\s*(?:-+|–|—|to|until)\s*{_END}|{_POINT})", re.I
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

TITLE_RE = re.compile(
    r"\b(engineer|developer|manager|intern|analyst|scientist|designer|consultant|architect|lead|director|"
    r"officer|administrator|specialist|associate|assistant|coordinator|researcher|programmer|technician|"
    r"president|founder|head|fellow|instructor|teacher|tutor|representative|executive|supervisor|advisor|"
    r"trainee|apprentice|writer|editor|accountant|nurse|strategist|recruiter|owner|contractor|freelancer|"
    r"freelance|devops|sre|ceo|cto|cfo|coo|vp)\b", re.I)
INSTITUTION_RE = re.compile(r"universit|college|institut|school|academy|polytechnic|hochschule|\bMIT\b|\bIIT\b", re.I)
DEGREE_RE = re.compile(
    r"\b(bachelor|master|doctor|ph\.?\s?d|b\.?\s?sc?|m\.?\s?sc?|b\.?a|m\.?a|mba|b\.?tech|m\.?tech|b\.?eng|"
    r"m\.?eng|diploma|associate|certificate|minor|major|honou?rs|a-levels?|gcse|high school)\b", re.I)
_COMPANY_SUFFIX = {"inc", "inc.", "llc", "ltd", "ltd.", "gmbh", "corp", "corp.", "co", "co.", "plc", "ag", "sa"}
_LOCATION_RE = re.compile(r"^[A-Z][\w .'’-]+,\s*([A-Z]{2,3}|[A-Z][a-z]+(?: [A-Z][a-z]+)*)$")
_REMOTE_RE = re.compile(r"^(remote|hybrid|on-?site)\b", re.I)
_TRAILING_LOCATION_RE = re.compile(r"^(.+?),\s*([^,]+,\s*[^,]+|remote|hybrid|on-?site)$", re.I)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\d/])(\+?\(?\d[\d\s().-]{5,}\d)(?!\d)")
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s|,;]+|\b(?:linkedin\.com|github\.com|gitlab\.com|bitbucket\.org)/[^\s|,;]+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:dev|io|com|me|net|org|app|ai|co)(?:/[^\s|,;]*)?(?![\w@])", re.I)


def split_dates(text: str) -> tuple[str, str]:
    """Return (text without its date range, date range) — date is '' when none is present."""
    m = DATE_RE.search(text)
    if not m:
        return text.strip(), ""
    rest = (text[: m.start()] + " " + text[m.end():]).strip(" ,|-–—()\t")
    return re.sub(r"\s{2,}", " ", rest), re.sub(r"\s*(?:-{1,3}|–|—)\s*", " – ", m.group().strip())


def is_location(text: str) -> bool:
    t = text.strip()
    if _REMOTE_RE.match(t):
        return True
    m = _LOCATION_RE.match(t)
    if not m or len(t) > 45:
        return False
    if m.group(1).lower() in _COMPANY_SUFFIX:
        return False
    return not (TITLE_RE.search(t) or DEGREE_RE.search(t) or INSTITUTION_RE.search(t))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t|,;·•")


def split_fields(text: str) -> list[str]:
    """Split a heading line into fields on tabs, wide gaps and newlines."""
    parts = re.split(r"\t|\n| {3,}", text)
    return [c for c in (_clean(p) for p in parts) if c]


_COMBO_RE = re.compile(r"\s+(?:—|–|\||@|at)\s+|\s+-\s+|,\s+")


def _split_combo(text: str) -> list[str]:
    parts = [p.strip() for p in _COMBO_RE.split(text, maxsplit=1) if p and p.strip()]
    return parts if len(parts) == 2 else [text]


# ---------------------------------------------------------------- entries


def build_entries(events: list[Event]) -> list[RawEntry]:
    """Group heading events with the bullets that follow them."""
    item_depths = sorted({e.depth for e in events if e.kind == "item"})
    header_depth = item_depths[0] if len(item_depths) > 1 else None
    entries: list[RawEntry] = []
    current: Optional[RawEntry] = None

    def start(fields: list[str], line: Optional[int], urls: list[str]) -> RawEntry:
        entry = RawEntry(fields=list(fields), bullets=[], line=line, urls=list(urls))
        entries.append(entry)
        return entry

    for ev in events:
        if ev.kind == "entry":
            current = start(ev.fields, ev.line, ev.urls)
            current.bullets.extend((t, ev.line) for t in ev.long_fields)
            continue
        if ev.kind == "item":
            text = ev.text.strip()
            if not text:
                continue
            looks_like_header = (
                ev.depth == header_depth
                or (header_depth is None and DATE_RE.search(text) and len(text) < 160
                    and ("\t" in text or "\n" in text))
            )
            if looks_like_header:
                current = start(split_fields(text), ev.line, ev.urls)
            else:
                if current is None:
                    current = start([], ev.line, [])
                current.bullets.append((_clean(text.replace("\n", " ").replace("\t", " ")), ev.line))
                current.urls.extend(ev.urls)
            continue
        for raw_line in ev.text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if len(line) > 110 and not DATE_RE.search(line[:60]):
                if current is None:
                    current = start([], ev.line, [])
                current.bullets.append((_clean(line.replace("\t", " ")), ev.line))
            elif current is not None and not current.bullets:
                current.fields.extend(split_fields(line))
                current.urls.extend(ev.urls)
            else:
                current = start(split_fields(line), ev.line, ev.urls)
    return [e for e in entries if e.fields or e.bullets]


def _bullets(raw: RawEntry) -> list[Bullet]:
    return [Bullet(id=new_id("blt"), text=t, source_line=ln) for t, ln in raw.bullets if t]


def _pull_dates_and_location(fields: list[str]) -> tuple[list[str], str, str]:
    rest: list[str] = []
    dates = ""
    for f in fields:
        if not dates:
            remainder, found = split_dates(f)
            if found:
                dates = found
                f = remainder
        if f:
            rest.append(f)
    location = ""
    for f in rest:
        if is_location(f):
            location = f
            rest.remove(f)
            break
    if not location:
        # "Employer, City, ST" / "Employer, Remote" written as one field
        for i, f in enumerate(rest):
            m = _TRAILING_LOCATION_RE.match(f)
            if m and is_location(m.group(2)):
                rest[i], location = m.group(1).strip(), m.group(2).strip()
                break
    return rest, dates, location


def make_experience(raw: RawEntry) -> Experience:
    rest, dates, location = _pull_dates_and_location(raw.fields)
    if len(rest) == 1:
        rest = _split_combo(rest[0])
    titles = [f for f in rest if TITLE_RE.search(f)]
    employer = title = ""
    uncertain = False
    if len(rest) >= 2:
        if len(titles) == 1:
            title = titles[0]
            employer = next(f for f in rest if f != title)
        else:
            employer, title = rest[0], rest[1]
            uncertain = True
        extras = [f for f in rest if f not in (employer, title)]
        if extras and not location:
            location = extras[0]
            uncertain = True
    elif len(rest) == 1:
        if titles:
            title = rest[0]
        else:
            employer = rest[0]
        uncertain = True
    else:
        uncertain = True
    if not dates:
        uncertain = True
    return Experience(id=new_id("exp"), employer=employer, title=title, location=location, dates=dates,
                      bullets=_bullets(raw), source_line=raw.line, uncertain=uncertain)


def make_education(raw: RawEntry) -> Education:
    rest, dates, location = _pull_dates_and_location(raw.fields)
    if len(rest) == 1:
        rest = _split_combo(rest[0])
    inst = next((f for f in rest if INSTITUTION_RE.search(f)), "")
    degree = next((f for f in rest if f != inst and DEGREE_RE.search(f)), "")
    uncertain = False
    leftovers = [f for f in rest if f not in (inst, degree)]
    if not inst and leftovers:
        inst = leftovers.pop(0)
        uncertain = True
    if not degree and leftovers:
        degree = leftovers.pop(0)
        uncertain = True
    details = [Bullet(id=new_id("blt"), text=f, source_line=raw.line) for f in leftovers] + _bullets(raw)
    return Education(id=new_id("edu"), institution=inst, degree=degree, location=location, dates=dates,
                     details=details, source_line=raw.line, uncertain=uncertain or not (inst and degree))


def make_project(raw: RawEntry) -> Project:
    rest, dates, _location = _pull_dates_and_location(raw.fields)
    name = tech = ""
    if rest:
        head = re.split(r"\s*\|\s*|\s+[—–]\s+", rest[0], maxsplit=1)
        name = head[0].strip()
        tech = head[1].strip() if len(head) > 1 else ""
        if not tech and len(rest) > 1:
            tech = ", ".join(rest[1:])
    link = next((u for u in raw.urls if not u.startswith("mailto:")), "")
    return Project(id=new_id("prj"), name=name, tech=tech, dates=dates, link=link, bullets=_bullets(raw),
                   source_line=raw.line, uncertain=not name)


def section_lines(events: list[Event]) -> list[tuple[str, Optional[int]]]:
    """Every textual line of a section, regardless of how it was marked up."""
    out: list[tuple[str, Optional[int]]] = []
    for ev in events:
        if ev.kind == "entry":
            parts = [*ev.fields, *ev.long_fields]
            if len(ev.fields) == 2 and not ev.long_fields:
                parts = [f"{ev.fields[0]}: {ev.fields[1]}"]
            out.extend((p, ev.line) for p in parts)
        else:
            out.extend((ln, ev.line) for ln in ev.text.split("\n"))
    cleaned = [(_clean(t.replace("\t", " ")), ln) for t, ln in out]
    return [(t, ln) for t, ln in cleaned if t]


def make_skills(events: list[Event]) -> list[SkillGroup]:
    groups: list[SkillGroup] = []
    loose: list[str] = []
    loose_line: Optional[int] = None
    for text, line in section_lines(events):
        category, sep, items_text = text.partition(":")
        if sep and len(category) <= 40 and items_text.strip():
            items = _split_list(items_text)
            groups.append(SkillGroup(id=new_id("skl"), category=category.strip(), items=items, source_line=line))
        else:
            loose.extend(_split_list(text))
            loose_line = loose_line or line
    if loose:
        groups.append(SkillGroup(id=new_id("skl"), category="Skills", items=loose, source_line=loose_line))
    return groups


def _split_list(text: str) -> list[str]:
    parts = re.split(r"\s*[,;|•·]\s*(?![^()]*\))", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def make_certifications(events: list[Event]) -> list[Certification]:
    certs: list[Certification] = []
    for text, line in section_lines(events):
        rest, date = split_dates(text)
        parts = [p.strip() for p in re.split(r"\s+[—–|-]\s+|,\s+", rest) if p.strip()]
        if not parts:
            continue
        certs.append(Certification(id=new_id("crt"), name=parts[0], issuer=", ".join(parts[1:]), date=date,
                                   source_line=line))
    return certs


def make_other(title: str, events: list[Event], line: Optional[int]) -> Optional[OtherSection]:
    items = [Bullet(id=new_id("blt"), text=t, source_line=ln) for t, ln in section_lines(events)]
    if not items:
        return None
    return OtherSection(id=new_id("oth"), title=title, items=items, source_line=line)


def make_summary(events: list[Event]) -> str:
    return " ".join(t for t, _ in section_lines(events))


# ---------------------------------------------------------------- contact


def _norm_url(url: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", url.strip().lower()).rstrip("/")


def extract_contact(header_text: str, urls: list[str]) -> Contact:
    contact = Contact()
    email = EMAIL_RE.search(header_text) or next(
        (EMAIL_RE.search(u) for u in urls if u.startswith("mailto:")), None)
    if email:
        contact.email = email.group()
    text_wo_email = EMAIL_RE.sub(" ", header_text)

    links: dict[str, str] = {}
    for u in urls:
        if not u.startswith("mailto:") and _norm_url(u):
            links.setdefault(_norm_url(u), u.strip())
    for m in URL_RE.finditer(text_wo_email):
        links.setdefault(_norm_url(m.group()), m.group().rstrip(".,)"))
    contact.links = list(links.values())
    text_wo_links = URL_RE.sub(" ", text_wo_email)

    for m in PHONE_RE.finditer(text_wo_links):
        digits = re.sub(r"\D", "", m.group(1))
        if 7 <= len(digits) <= 15 and not re.fullmatch(r"(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}", m.group(1).strip()):
            contact.phone = m.group(1).strip()
            break

    segments = [s.strip() for s in re.split(r"[\n\t|•·◦⋄]| {3,}", text_wo_links) if s.strip()]
    for seg in segments:
        if re.fullmatch(r"[^\W\d_][^\d@_/|]{1,60}", seg) and 2 <= len(seg.split()) <= 5 and not is_location(seg):
            contact.name = re.sub(r"\s+", " ", seg)
            break
    for seg in segments:
        if seg != contact.name and is_location(seg):
            contact.location = seg
            break
    return contact
