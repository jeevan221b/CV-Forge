"""Deterministic job-description analysis. No network, no AI.

The JD is split at its headings; each bullet or sentence under a requirement-bearing heading
becomes one editable Requirement with a category, an importance and detected keywords.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from ..lexicon import STOPWORDS, canonical_term, find_terms, normalize_ws, stem
from ..models import JDAnalysis, Requirement, new_id

_GENERIC_JD_WORDS = frozenset("""
experience company customers customer building build services service engineers engineer engineering software
product products systems system design strong development develop technical business support across people
world opportunity responsible collaborate collaboration communication problems solutions growth culture
looking mission impact great start startup office remote hybrid benefits salary apply application process
professional things other their there these those about which would should could deliver delivering working
""".split())

_HEADINGS: list[tuple[str, re.Pattern[str]]] = [
    ("other", re.compile(r"about (?:the|this) (?:role|job|position|opportunity)|overview|^summary$|^description$", re.I)),
    ("preferred", re.compile(r"nice[- ]to[- ]have|preferred|bonus|plus(?:es)?$|desir|good to have|"
                             r"extra credit|would be great|stand out", re.I)),
    ("responsibility", re.compile(r"responsibilit|what you(?:'|’)?ll do|what you will do|the role|your role|"
                                  r"day[- ]to[- ]day|duties|you will|in this role|key tasks|what you(?:'|’)?ll be doing", re.I)),
    ("required", re.compile(r"requirement|qualification|must[- ]have|what you(?:'|’)?ll need|what we(?:'|’)?re looking for|"
                            r"who you are|you have|about you|skills|what you bring|experience|essential|"
                            r"minimum|basic|your profile|what you need", re.I)),
    ("ignore", re.compile(r"benefit|perks|compensation|salary|about (?:us|the company|the team)|who we are|"
                          r"equal opportunity|how to apply|our mission|our values|what we offer|why join|"
                          r"location|diversity|our stack$", re.I)),
]
_BULLET_RE = re.compile(r"^\s*(?:[-•●▪■◦‣∙·*–]|\d{1,2}[.)])\s+")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)", re.I)
_QUALIFICATION_RE = re.compile(r"\b(degree|bachelor|master|ph\.?d|diploma|certif|licen[sc]e|clearance|"
                               r"authori[sz]ed to work|visa|fluent|fluency)\b", re.I)
_PREFERRED_INLINE = re.compile(r"\b(preferred|nice to have|a plus|bonus|ideally|desirable|advantage)\b", re.I)
_MUST_INLINE = re.compile(r"\b(must|required|essential|mandatory|minimum)\b", re.I)
_TITLE_LABEL = re.compile(r"^(?:job\s+title|position|role|title)\s*[:\-–]\s*(.+)$", re.I)
_COMPANY_LABEL = re.compile(r"^(?:company|employer|organi[sz]ation)\s*[:\-–]\s*(.+)$", re.I)
_TITLE_WORDS = re.compile(r"\b(engineer|developer|manager|analyst|scientist|designer|architect|lead|director|"
                          r"consultant|specialist|administrator|intern|researcher|officer|coordinator|"
                          r"programmer|technician|devops|sre|head of)\b", re.I)


def _heading_kind(line: str) -> Optional[str]:
    text = line.strip().rstrip(":").strip("*#_ ")
    if not text or len(text) > 60 or _BULLET_RE.match(line) or text.endswith("."):
        return None
    if len(text.split()) > 8:
        return None
    for kind, pat in _HEADINGS:
        if pat.search(text):
            return kind
    is_label = line.strip().endswith(":") or text.isupper() or line.strip().startswith(("#", "**"))
    return "other" if is_label and len(text.split()) <= 5 else None


def _split_statements(lines: list[str]) -> list[str]:
    """Bullets stay whole; unbulleted prose is split into sentences."""
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if _BULLET_RE.match(line):
            out.append(normalize_ws(_BULLET_RE.sub("", line)))
        elif out and line.startswith((" ", "\t")) and not line.strip()[:1].isupper():
            out[-1] = normalize_ws(out[-1] + " " + line)
        else:
            out.extend(normalize_ws(s) for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", line.strip()) if s.strip())
    return [s.rstrip(" .;") for s in out if len(s) > 3]


def classify_statement(text: str, block: str) -> tuple[str, str]:
    """(category, importance) for one statement inside a block of the given kind."""
    keywords = find_terms(text)
    if block == "responsibility":
        return "responsibility", "important"
    preferred = block == "preferred" or bool(_PREFERRED_INLINE.search(text))
    if _YEARS_RE.search(text):
        return "experience", "nice" if preferred else "must"
    if _QUALIFICATION_RE.search(text) and len(keywords) <= 1:
        return "qualification", "nice" if preferred else "important"
    if preferred:
        return "preferred_skill", "nice"
    importance = "must" if (block == "required" or _MUST_INLINE.search(text)) else "important"
    return "required_skill", importance


def guess_title(lines: list[str]) -> tuple[str, str]:
    title = employer = ""
    for line in lines[:15]:
        text = line.strip().strip("#* ")
        if not text:
            continue
        m = _TITLE_LABEL.match(text)
        if m and not title:
            title = m.group(1).strip()
        m = _COMPANY_LABEL.match(text)
        if m and not employer:
            employer = re.sub(r"\s*\(.*?\)\s*$", "", m.group(1)).strip()
    if not title:
        for line in lines[:8]:
            text = line.strip().strip("#* ")
            if text and len(text) <= 80 and _TITLE_WORDS.search(text) and not text.endswith("."):
                at = re.split(r"\s+(?:at|@)\s+|\s+[-–—|]\s+", text, maxsplit=1)
                title = at[0].strip()
                if len(at) > 1 and not employer and not re.search(r"remote|hybrid|full[- ]time|part[- ]time", at[1], re.I):
                    employer = at[1].strip()
                break
    return title, employer


def analyze_jd(text: str) -> JDAnalysis:
    lines = text.replace("\r\n", "\n").split("\n")
    title, employer = guess_title(lines)
    notes: list[str] = []

    blocks: list[tuple[str, list[str]]] = [("intro", [])]
    for line in lines:
        kind = _heading_kind(line)
        if kind:
            blocks.append((kind, []))
        else:
            blocks[-1][1].append(line)

    structured = any(kind in ("required", "preferred", "responsibility") for kind, _ in blocks)
    requirements: list[Requirement] = []
    seen: set[str] = set()
    covered_terms: set[str] = set()

    def add(text_: str, category: str, importance: str, keywords: list[str]) -> None:
        key = text_.lower()
        if key in seen or not text_:
            return
        seen.add(key)
        covered_terms.update(keywords)
        requirements.append(Requirement(id=new_id("req"), text=text_, category=category,  # type: ignore[arg-type]
                                        importance=importance, keywords=keywords))  # type: ignore[arg-type]

    for kind, body in blocks:
        if kind in ("ignore",) or (structured and kind in ("intro", "other")):
            continue
        for statement in _split_statements(body):
            keywords = find_terms(statement)
            if not structured:
                # Unstructured prose: keep only sentences that actually state a requirement.
                if not (keywords or _YEARS_RE.search(statement) or _QUALIFICATION_RE.search(statement)):
                    continue
            if _TITLE_LABEL.match(statement) or _COMPANY_LABEL.match(statement):
                continue
            category, importance = classify_statement(statement, kind if structured else "required")
            add(statement, category, importance, keywords)

    # Technologies mentioned anywhere (e.g. in the intro) but not attached to a requirement above.
    relevant_text = "\n".join("\n".join(body) for kind, body in blocks if kind != "ignore")
    for term in find_terms(relevant_text):
        if term not in covered_terms:
            add(f"Mentions {term}", "technology", "nice", [term])

    # Recurring domain vocabulary. Reported as terminology only; it never counts towards the match score.
    counts = Counter(stem(w) for w in re.findall(r"[A-Za-z]{5,}", relevant_text)
                     if w.lower() not in STOPWORDS and w.lower() not in _GENERIC_JD_WORDS)
    surface = {stem(w): w.lower() for w in reversed(re.findall(r"[A-Za-z]{5,}", relevant_text))}
    lexicon_stems = {stem(w) for t in covered_terms for w in t.split()}
    added = 0
    for word, count in counts.most_common():
        if count < 3 or added >= 6:
            break
        if word in lexicon_stems or stem(title.lower()) == word or word in {stem(w) for w in title.split()}:
            continue
        add(f"Recurring term: {surface[word]}", "terminology", "nice", [surface[word]])
        added += 1

    if not structured:
        notes.append("No standard headings (Requirements, Responsibilities, Nice to have) were found, so "
                     "requirements were inferred sentence by sentence. Review the list carefully.")
    if not requirements:
        notes.append("No requirements could be extracted. Add them manually.")
    if not title:
        notes.append("The job title could not be determined — please enter it.")
    return JDAnalysis(job_title=title, employer=employer, requirements=requirements, notes=notes)


def normalise_keywords(keywords: list[str]) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        term = canonical_term(kw)
        if term and term not in out:
            out.append(term)
    return out
