"""Heuristic LaTeX resume parser.

The parser never executes LaTeX. It reads the source as text, splits it at section commands,
and recognises three structures inside a section: entry headings (macros with two or more
arguments such as \\resumeSubheading / \\cventry, or \\subsection), list items (\\item and
item-like macros) and loose text lines. Anything it has to guess at is reported as a warning.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from . import heuristics as h
from .assemble import ParsedSection, ParseResult, assemble_profile

_NAME_RE = re.compile(r"[A-Za-z@]+")
_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_SECTION_RE = re.compile(
    r"\\(?![Ss]ub)([A-Za-z]*[Ss]ection[A-Za-z]*)\*?\s*(?:\[[^\]]*\]\s*)?(?=\{)"
    r"|\\begin\{([A-Za-z]*[Ss]ection[A-Za-z]*)\}\s*(?=\{)"
)

_FORMAT = set("""
textbf textit textsc texttt textrm textsf textmd textup textsl textnormal emph underline uline mbox text
small footnotesize scriptsize tiny normalsize large Large LARGE huge Huge bfseries itshape scshape mdseries
upshape rmfamily sffamily ttfamily normalfont centering raggedright raggedleft noindent selectfont sloppy
fussy protect relax leavevmode strut hrulefill dotfill titlerule smallskip medskip bigskip newpage clearpage
pagebreak nopagebreak linebreak nolinebreak maketitle makecvtitle null vfill hline toprule midrule bottomrule
centerline section subsection subsubsection paragraph textsuperscript textsubscript item makecvheader
""".split())

_SYMBOLS = {
    "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^", "LaTeX": "LaTeX", "TeX": "TeX",
    "textbar": "|", "textbullet": "•", "bullet": "•", "cdot": "·", "dots": "…", "ldots": "…",
    "textendash": "–", "textemdash": "—", "quad": " ", "qquad": " ", "hfill": "\t", "par": "\n",
    "newline": "\n", "textgreater": ">", "textless": "<", "textquotedblleft": '"', "textquotedblright": '"',
    "enspace": " ", "thinspace": " ", "space": " ", "sep": " | ", "textperiodcentered": "·", "vline": "|",
    "slash": "/", "ss": "ß", "ae": "æ", "o": "ø", "aa": "å", "tabularnewline": "\n", "copyright": "©",
}

# macro -> number of mandatory arguments that carry no resume text
_DROP = {
    "vspace": 1, "hspace": 1, "color": 1, "textcolor": 1, "fontsize": 2, "label": 1, "includegraphics": 1,
    "setlength": 2, "addtolength": 2, "pagestyle": 1, "thispagestyle": 1, "input": 1, "include": 1,
    "usepackage": 1, "rule": 2, "faIcon": 1, "fontfamily": 1, "hypersetup": 1, "definecolor": 3,
    "raisebox": 1, "parbox": 1, "colorbox": 1, "multicolumn": 2, "extracolsep": 1, "renewcommand": 2,
    "newcommand": 2, "setcounter": 2, "pdfgentounicode": 0, "kern": 0, "vskip": 0, "hskip": 0,
    "phantom": 1, "hyperlink": 1, "fontspec": 1, "setmainfont": 1, "geometry": 1, "titlespacing": 4,
    "titleformat": 5, "linespread": 1, "cvitemwithcomment": 0, "pagenumbering": 1, "columnbreak": 0,
}
_LIST_ENVS = {"itemize", "enumerate", "description", "cvitems", "itemize*", "enumerate*", "highlights",
              "tightemize", "bullets", "list", "compactitem", "achievements", "cvlist"}
_TABLE_ENVS = {"tabular", "tabular*", "tabularx", "tabulary", "longtable", "array", "minipage", "multicols"}
_KNOWN_ENVS = _LIST_ENVS | _TABLE_ENVS | {"document", "center", "flushleft", "flushright", "adjustwidth",
                                           "cventries", "cvskills", "cvhonors", "cvparagraph", "onecolentry",
                                           "header", "samepage", "minipage", "paracol", "small", "large"}
_ITEMLIKE = re.compile(r"item|bullet|achievement|highlight", re.I)
_LIST_BOUNDARY = re.compile(r"(list|items?|entries)(start|end|begin|finish)$", re.I)
_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "c": "\u0327",
            "v": "\u030c", "=": "\u0304", ".": "\u0307", "u": "\u0306", "H": "\u030b", "r": "\u030a"}
_ACCENT_RE = re.compile(r"\\(['`^\"~=.]|[cvuHr](?=\{))\s*\{?([A-Za-z])\}?")


@dataclass
class Ctx:
    urls: list[str] = field(default_factory=list)
    unknown: set[str] = field(default_factory=set)
    custom: set[str] = field(default_factory=set)


def strip_comments(source: str) -> str:
    """Remove comments but keep every line break so line numbers stay valid."""
    return "\n".join(_COMMENT_RE.sub("", line) for line in source.replace("\r\n", "\n").split("\n"))


def read_group(s: str, i: int) -> Optional[tuple[str, int]]:
    """Read a balanced {...} group starting at or after whitespace from position i."""
    n = len(s)
    while i < n and s[i] in " \t\n":
        i += 1
    if i >= n or s[i] != "{":
        return None
    depth, j = 0, i
    while j < n:
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1: j], j + 1
        j += 1
    return None


def _skip_optional(s: str, i: int) -> int:
    m = re.compile(r"[ \t]*\[[^\]]*\]").match(s, i)
    return m.end() if m else i


def _read_groups(s: str, i: int, limit: int = 12) -> tuple[list[str], int]:
    groups: list[str] = []
    while len(groups) < limit:
        got = read_group(s, _skip_optional(s, i) if groups else i)
        if not got:
            break
        groups.append(got[0])
        i = got[1]
    return groups, i


def _skip_env_args(s: str, i: int, env: str) -> int:
    i = _skip_optional(s, i)
    if env in _TABLE_ENVS:
        while True:
            i = _skip_optional(s, i)
            got = read_group(s, i) if s[i: i + 1] == "{" else None
            if not got:
                break
            i = got[1]
    return i


def delatex(s: str, ctx: Optional[Ctx] = None) -> str:
    """Convert a LaTeX fragment to plain text. Tolerates unbalanced braces."""
    ctx = ctx if ctx is not None else Ctx()
    s = _ACCENT_RE.sub(lambda m: unicodedata.normalize("NFC", m.group(2) + _ACCENTS[m.group(1)]), s)
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            nxt = s[i + 1] if i + 1 < n else ""
            if nxt == "\\":
                out.append("\n")
                i += 2
                if s[i: i + 1] == "*":
                    i += 1
                i = _skip_optional(s, i)
                continue
            if nxt in "&%$#_{}":
                out.append(nxt)
                i += 2
                continue
            if nxt in " ,;!:/\n" or nxt == "":
                out.append(" ")
                i += 2
                continue
            m = _NAME_RE.match(s, i + 1)
            if not m:
                i += 2
                continue
            name, i = m.group(), m.end()
            if s[i: i + 1] == "*":
                i += 1
            if name == "href":
                groups, i = _read_groups(s, i, 2)
                if groups:
                    ctx.urls.append(groups[0].strip())
                    label = delatex(groups[1], ctx).strip() if len(groups) > 1 else ""
                    out.append(label or groups[0].strip())
                continue
            if name == "url":
                got = read_group(s, i)
                if got:
                    ctx.urls.append(got[0].strip())
                    out.append(got[0].strip())
                    i = got[1]
                continue
            if name in ("begin", "end"):
                got = read_group(s, i)
                env = got[0] if got else ""
                i = got[1] if got else i
                if name == "begin":
                    i = _skip_env_args(s, i, env)
                if env and env not in _KNOWN_ENVS and "section" not in env.lower() and env not in ctx.custom:
                    ctx.unknown.add(f"{env} (environment)")
                out.append("\n")
                continue
            if name == "item":
                i = _skip_optional(s, i)
                out.append("\n• ")
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name])
            elif name in _DROP:
                i = _skip_optional(s, i)
                for _ in range(_DROP[name]):
                    got = read_group(s, i)
                    if not got:
                        break
                    i = got[1]
                if name in ("vskip", "hskip", "kern"):
                    dim = re.compile(r"\s*-?[\d.]+\s*(pt|em|ex|in|cm|mm|bp)").match(s, i)
                    i = dim.end() if dim else i
            elif re.fullmatch(r"fa[A-Z][A-Za-z]*", name):
                pass  # FontAwesome icon
            elif name not in _FORMAT:
                ctx.unknown.add(name)
            while i < n and s[i] in " \t":  # TeX swallows spaces after a control word
                i += 1
            continue
        if ch == "}":
            if re.compile(r"\s*\{").match(s, i + 1):
                out.append("\t")
            i += 1
        elif ch in "{$":
            i += 1
        elif ch == "~":
            out.append(" ")
            i += 1
        elif ch == "&":
            out.append("\t")
            i += 1
        elif s.startswith("---", i):
            out.append("—")
            i += 3
        elif s.startswith("--", i):
            out.append("–")
            i += 2
        elif s.startswith("``", i) or s.startswith("''", i):
            out.append('"')
            i += 2
        else:
            out.append(ch)
            i += 1
    text = "".join(out)
    text = re.sub(r"[ \u00a0]+", " ", text)
    lines = [ln.strip(" ") for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n ")


class _Scanner:
    """Splits a section body into entry / item / text events."""

    def __init__(self, body: str, base: int, line_at, ctx: Ctx):
        self.s, self.base, self.line_at, self.ctx = body, base, line_at, ctx
        self.events: list[h.Event] = []
        self.buf: list[str] = []
        self.buf_start = 0
        self.in_item = False
        self.depth = 0
        self.item_depth = 0

    def _flush(self, pos: int) -> None:
        raw = "".join(self.buf)
        self.buf = []
        if raw.strip():
            local = Ctx(custom=self.ctx.custom)
            text = delatex(raw, local)
            self.ctx.unknown |= local.unknown
            if text.strip():
                self.events.append(h.Event(
                    kind="item" if self.in_item else "text", text=text, urls=local.urls,
                    line=self.line_at(self.base + self.buf_start), depth=self.item_depth if self.in_item else 0))
        self.in_item = False
        self.buf_start = pos

    def _entry(self, name: str, groups: list[str], pos: int) -> None:
        local = Ctx(custom=self.ctx.custom)
        fields: list[str] = []
        long_fields: list[str] = []
        for g in groups:
            if "\\item" in g:
                sub = _Scanner(g, self.base + pos, self.line_at, local).run()
                long_fields.extend(e.text for e in sub if e.kind == "item")
                fields.extend(f for e in sub if e.kind == "text" for f in h.split_fields(e.text))
                continue
            text = delatex(g, local)
            if len(text) > 110:
                long_fields.append(re.sub(r"\s+", " ", text))
            else:
                fields.extend(h.split_fields(text))
        self.ctx.unknown |= local.unknown
        self.events.append(h.Event(kind="entry", fields=fields, long_fields=long_fields, urls=local.urls,
                                   line=self.line_at(self.base + pos), macro=name))

    def run(self) -> list[h.Event]:
        s, n, i = self.s, len(self.s), 0
        while i < n:
            if s[i] != "\\":
                self.buf.append(s[i])
                i += 1
                continue
            m = _NAME_RE.match(s, i + 1)
            if not m:
                self.buf.append(s[i: i + 2])
                i += 2
                continue
            name, start, i = m.group(), i, m.end()
            if s[i: i + 1] == "*":
                i += 1
            if name == "item":
                self._flush(start)
                i = _skip_optional(s, i)
                self.in_item, self.item_depth = True, self.depth
            elif name in ("begin", "end"):
                got = read_group(s, i)
                env = got[0] if got else ""
                if env in _LIST_ENVS or (env not in _KNOWN_ENVS and _ITEMLIKE.search(env)):
                    self._flush(start)
                    i = got[1] if got else i
                    if name == "begin":
                        i = _skip_optional(s, i)
                        self.depth += 1
                    else:
                        self.depth = max(0, self.depth - 1)
                    self.buf_start = i
                elif name == "begin" and env and env not in _KNOWN_ENVS:
                    groups, j = _read_groups(s, got[1])
                    if len(groups) >= 2:  # e.g. \begin{rSubsection}{Employer}{Dates}{Title}{Place}
                        self._flush(start)
                        self._entry(env, groups, start)
                        self.ctx.custom.add(env)
                        i = j
                        self.buf_start = i
                    else:
                        self.buf.append(s[start:i])
                else:
                    self.buf.append(s[start:i])
            elif name in ("subsection", "subsubsection", "paragraph"):
                groups, j = _read_groups(s, i, 1)
                self._flush(start)
                self._entry(name, groups, start)
                i = j
                self.buf_start = i
            elif name in _FORMAT or name in _SYMBOLS or name in _DROP or name in ("href", "url"):
                self.buf.append(s[start:i])
            else:
                groups, j = _read_groups(s, i)
                if len(groups) >= 2:
                    self._flush(start)
                    self._entry(name, groups, start)
                    self.ctx.custom.add(name)
                    i = j
                    self.buf_start = i
                elif len(groups) == 1 and _ITEMLIKE.search(name):
                    self._flush(start)
                    self.in_item, self.item_depth = True, self.depth
                    self.buf.append(groups[0])
                    self._flush(j)
                    i = j
                elif not groups and _LIST_BOUNDARY.search(name):
                    self._flush(i)
                else:
                    self.buf.append(s[start:i])
        self._flush(n)
        return self.events


def _preamble_contact(src: str, ctx: Ctx) -> dict[str, str]:
    """Contact macros used by moderncv / awesome-cv style classes."""
    def arg(macro: str, count: int = 1) -> list[str]:
        m = re.search(rf"\\{macro}\s*(?:\[[^\]]*\])?\s*(?=\{{)", src)
        if not m:
            return []
        groups, _ = _read_groups(src, m.end(), count)
        return [delatex(g) for g in groups]

    out: dict[str, str] = {}
    name = arg("name", 2) or (arg("firstname") + (arg("familyname") or arg("lastname")))
    if name and all(len(p) < 60 for p in name):
        out["name"] = " ".join(p for p in name if p).strip()
    for key, macros in (("email", ("email",)), ("phone", ("phone", "mobile")), ("location", ("address",))):
        for macro in macros:
            values = arg(macro, 3 if key == "location" else 1)
            if values and "#" not in "".join(values):
                out[key] = ", ".join(v for v in values if v)
                break
    for m in re.finditer(r"\\social\[(\w+)\]\s*\{([^}]*)\}|\\(linkedin|github|gitlab|homepage)\s*\{([^}#]*)\}", src):
        kind, user = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        prefix = {"linkedin": "linkedin.com/in/", "github": "github.com/", "gitlab": "gitlab.com/"}.get(kind, "")
        if user.strip():
            ctx.urls.append(prefix + user.strip())
    return out


def parse_latex(source: str) -> ParseResult:
    src = strip_comments(source)
    line_starts = [0] + [m.end() for m in re.finditer("\n", src)]

    def line_at(pos: int) -> int:
        return bisect.bisect_right(line_starts, pos)

    ctx = Ctx()
    ctx.custom = set(re.findall(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)", src))
    ctx.custom |= set(re.findall(r"\\(?:re)?newenvironment\*?\s*\{([A-Za-z@*]+)\}", src))
    ctx.custom |= set(re.findall(r"\\def\\([A-Za-z@]+)", src))

    begin = re.search(r"\\begin\{document\}", src)
    end = re.search(r"\\end\{document\}", src)
    body_start = begin.end() if begin else 0
    body = src[body_start: end.start() if end and end.start() > body_start else len(src)]
    warnings: list[str] = []
    if not begin:
        warnings.append("No \\begin{document} found — the whole file was treated as resume content.")

    header_ctx = Ctx(custom=ctx.custom)
    overrides = _preamble_contact(src, header_ctx)

    marks: list[tuple[int, int, str]] = []  # (start, body_start, title)
    for m in _SECTION_RE.finditer(body):
        got = read_group(body, m.end())
        if got:
            marks.append((m.start(), got[1], re.sub(r"\s+", " ", delatex(got[0])).strip()))

    header_raw = body[: marks[0][0]] if marks else body
    header_text = delatex(header_raw, header_ctx)
    ctx.unknown |= header_ctx.unknown

    sections: list[ParsedSection] = []
    text_parts = [header_text]
    for idx, (start, content_start, title) in enumerate(marks):
        stop = marks[idx + 1][0] if idx + 1 < len(marks) else len(body)
        chunk = re.sub(r"\\end\{[A-Za-z]*[Ss]ection[A-Za-z]*\}", "", body[content_start:stop])
        events = _Scanner(chunk, body_start + content_start, line_at, ctx).run()
        sections.append(ParsedSection(title=title, events=events, line=line_at(body_start + start)))
        text_parts.append(f"{title.upper()}\n{delatex(chunk)}")

    extracted = re.sub(r"\n{3,}", "\n\n", "\n\n".join(p for p in text_parts if p.strip())).replace("\t", "  ")

    if not marks:
        # No recognisable section commands: fall back to the plain-text heuristics.
        from .text_parser import parse_plain_text

        result = parse_plain_text(extracted, urls=header_ctx.urls)
        result.warnings.insert(0, "No LaTeX section commands were recognised; headings were inferred from the text. "
                                  "Review every field.")
        result.warnings = warnings + result.warnings
        return result

    profile, more = assemble_profile(header_text, header_ctx.urls, sections, overrides)
    warnings.extend(more)

    used_structurally = sorted({e.macro for s in sections for e in s.events
                                if e.kind == "entry" and e.macro not in ("subsection", "subsubsection", "paragraph")})
    if used_structurally:
        warnings.append("Custom macros/environments interpreted as entry headings by argument content, not by their "
                        "definition: " + ", ".join(f"\\{n}" for n in used_structurally)
                        + ". Verify employers, titles and dates.")
    unknown = sorted(n for n in ctx.unknown if n not in ctx.custom or n.endswith("(environment)"))
    custom_dropped = sorted(n for n in ctx.unknown if n in ctx.custom)
    if unknown:
        warnings.append("Unrecognised LaTeX commands were skipped (their text arguments were kept): "
                        + ", ".join(f"\\{n}" for n in unknown[:15]) + ".")
    if custom_dropped:
        warnings.append("Custom macros with unknown meaning were skipped (their text arguments were kept): "
                        + ", ".join(f"\\{n}" for n in custom_dropped[:15]) + ". Check that no content was lost.")
    return ParseResult(profile=profile, extracted_text=extracted, warnings=warnings)
