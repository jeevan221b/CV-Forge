"""Escaping of untrusted text for LaTeX. Template commands never pass through here; resume
text always does."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "|": r"\textbar{}",
}
_UNICODE = {
    "–": "--", "—": "---", "‒": "--", "―": "---", "−": "-",
    "‘": "`", "’": "'", "“": "``", "”": "''", "…": r"\ldots{}",
    " ": "~", " ": "~", "•": r"\textbullet{}", "·": r"\textperiodcentered{}",
    "→": r"$\rightarrow$", "←": r"$\leftarrow$", "≥": r"$\geq$", "≤": r"$\leq$",
    "×": r"$\times$", "±": r"$\pm$", "≈": r"$\approx$", "°": r"\textdegree{}",
    "€": r"\texteuro{}", "£": r"\pounds{}", "©": r"\copyright{}",
    "®": r"\textregistered{}", "™": r"\texttrademark{}",
}
_TABLE = {**_SPECIALS, **_UNICODE}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _TABLE))
_CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏  ﻿]")


def escape_latex(text: str, multiline: bool = False) -> str:
    """Escape plain text for LaTeX.

    Single-line mode folds all whitespace (including line breaks) into spaces. Multiline mode keeps
    blank lines as paragraph breaks and folds single line breaks into spaces.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = _CONTROL_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if multiline:
        paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
        return "\n\n".join(_escape_line(p) for p in paragraphs if p)
    return _escape_line(re.sub(r"\s+", " ", text).strip())


def _escape_line(text: str) -> str:
    # Keep literal ASCII hyphen runs from turning into en/em dash ligatures ("--verbose").
    text = re.sub(r"-(?=-)", "-\u0000", text)
    out = _ESCAPE_RE.sub(lambda m: _TABLE[m.group()], text)
    return out.replace("\u0000", "{}")


_URL_OK = re.compile(r"^(?:https?://|mailto:)[^\s]+$", re.I)


def normalise_url(value: str) -> str:
    """Return an http(s)/mailto URL, or '' if the value cannot safely be used as a link target."""
    v = re.sub(r"\s+", "", value or "")
    if not v:
        return ""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", v) and not _URL_OK.match(v):
        return ""  # javascript:, file:, etc.
    if not _URL_OK.match(v):
        v = ("mailto:" + v) if re.fullmatch(r"[^@/]+@[^@/]+\.[A-Za-z]{2,}", v) else "https://" + v
    return v


def escape_url(value: str) -> str:
    """Encode a URL so it is inert inside \\href{...}, even when used within another macro's argument."""
    url = normalise_url(value)
    if not url:
        return ""
    encoded = quote(url, safe=":/?#[]@!&'()*+,;=%-._")
    return re.sub(r"([%#&_])", r"\\\1", encoded)
