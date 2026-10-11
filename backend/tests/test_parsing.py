"""LaTeX parsing, plain-text/PDF parsing and profile validation."""
import io

from pypdf import PdfWriter

from app.models import ResumeProfile, build_evidence, profile_issues
from app.parsing.latex_parser import delatex, parse_latex, strip_comments
from app.parsing.pdf_extract import extract_pdf_text
from app.parsing.text_parser import parse_plain_text

from .conftest import text_pdf


def test_sample_resume_is_parsed_into_structured_profile(sample_tex):
    result = parse_latex(sample_tex)
    p = result.profile
    assert p.contact.name == "Avery Quill"
    assert p.contact.email == "avery.quill@example.com"
    assert p.contact.phone == "555-0142"
    assert p.contact.location == "Portland, OR"
    assert any("github.com/averyquill-sample" in u for u in p.contact.links)
    assert p.summary.startswith("Backend-focused software engineer")
    assert "trailing comment" not in p.summary

    first, second = p.experience
    assert (first.employer, first.title, first.dates) == ("Lanternfish Logistics", "Software Engineer", "Mar 2022 – Present")
    assert (second.employer, second.title, second.location) == ("Peregrine Analytics", "Junior Developer", "Remote")
    assert len(first.bullets) == 4 and len(second.bullets) == 3
    assert not first.uncertain

    assert {g.category: g.items for g in p.skills}["Languages"] == ["Python", "SQL", "TypeScript", "JavaScript", "Bash"]
    assert p.projects[0].name == "Trailhead Tracker" and p.projects[0].tech == "Python, Flask, SQLite"
    assert p.education[0].institution == "Cascadia State University"
    assert p.education[0].degree == "Bachelor of Science in Computer Science"
    assert p.certifications[0].name == "AWS Certified Cloud Practitioner"
    assert p.certifications[0].date == "2023"


def test_latex_escapes_are_decoded_and_facts_are_traceable(sample_tex):
    p = parse_latex(sample_tex).profile
    bullets = [b for e in p.experience for b in e.bullets]
    assert any("service & cut regressions" in b.text for b in bullets)
    assert any("30% of the support staff" in b.text for b in bullets)
    assert any("customer_events pipeline" in b.text for b in bullets)
    lines = sample_tex.splitlines()
    for b in bullets:  # every bullet points back at the source line it came from
        assert b.origin == "document" and b.source_line
        assert b.text.split()[0] in lines[b.source_line - 1]


def test_custom_macros_are_reported_not_silently_trusted(sample_tex):
    warnings = " ".join(parse_latex(sample_tex).warnings)
    assert "\\resumeSubheading" in warnings and "Verify" in warnings


def test_moderncv_style_document():
    src = r"""
\documentclass{moderncv}
\name{Rowan}{Thistle}
\email{rowan@example.org}
\phone[mobile]{+1 555 0100}
\social[github]{rowanthistle}
\begin{document}
\makecvtitle
\section{Experience}
\cventry{2019--2021}{Data Analyst}{Marigold Labs}{Leeds, UK}{}{
  \begin{itemize}
    \item Built weekly sales reports in SQL
    \item Automated checks with Python
  \end{itemize}}
\section{Education}
\cventry{2015--2018}{BSc Mathematics}{University of Northbridge}{}{}{}
\section{Skills}
\cvitem{Languages}{Python, SQL, R}
\end{document}
"""
    p = parse_latex(src).profile
    assert p.contact.name == "Rowan Thistle" and p.contact.email == "rowan@example.org"
    assert any("github.com/rowanthistle" in u for u in p.contact.links)
    e = p.experience[0]
    assert (e.title, e.employer, e.dates, e.location) == ("Data Analyst", "Marigold Labs", "2019 – 2021", "Leeds, UK")
    assert [b.text for b in e.bullets] == ["Built weekly sales reports in SQL", "Automated checks with Python"]
    assert p.education[0].institution == "University of Northbridge" and p.education[0].degree == "BSc Mathematics"
    assert p.skills[0].category == "Languages" and p.skills[0].items == ["Python", "SQL", "R"]


def test_plain_itemize_layout_with_hfill():
    src = r"""
\begin{document}
{\LARGE Juno Marlowe}\\ juno@example.net
\section*{Work Experience}
\textbf{Kestrel Robotics} \hfill Jan 2021 -- Dec 2023 \\
\textit{Firmware Engineer} \hfill Austin, TX
\begin{itemize}
  \item Wrote motor control firmware in C
\end{itemize}
\end{document}
"""
    e = parse_latex(src).profile.experience[0]
    assert (e.employer, e.title, e.location, e.dates) == ("Kestrel Robotics", "Firmware Engineer", "Austin, TX", "Jan 2021 – Dec 2023")
    assert e.bullets[0].text == "Wrote motor control firmware in C"


def test_ambiguous_entry_is_flagged_uncertain():
    src = r"""\begin{document}
\section{Experience}
\textbf{Quartz \& Vine} \hfill 2020 -- 2021 \\ \textit{Harbor Collective}
\begin{itemize}\item Did things\end{itemize}
\end{document}"""
    result = parse_latex(src)
    assert result.profile.experience[0].uncertain
    assert any("guesswork" in w for w in result.warnings)


def test_unknown_macros_and_missing_sections_produce_warnings():
    result = parse_latex(r"\begin{document}\mystery{Some text} with no headings at all\end{document}")
    assert any("section" in w.lower() for w in result.warnings)
    result = parse_latex(r"\begin{document}\section{Summary}\weirdmacro{Kept text} here\end{document}")
    assert "Kept text" in result.profile.summary
    assert any("weirdmacro" in w for w in result.warnings)


def test_comment_stripping_keeps_line_numbers_and_escaped_percent():
    src = "a % gone\n100\\% kept % gone\nlast"
    out = strip_comments(src)
    assert out.splitlines() == ["a ", "100\\% kept ", "last"]
    assert delatex(r"\textbf{A \& B} --- \href{https://x.example}{link} 50\%") == "A & B — link 50%"


def test_plain_text_parser_handles_typical_pdf_text():
    text = """Avery Quill
avery.quill@example.com | 555-0142 | Portland, OR

EXPERIENCE
Software Engineer                                   Mar 2022 – Present
Lanternfish Logistics, Portland, OR
  • Built a FastAPI service that validates shipment manifests and
    processes about 40,000 requests per day
  • Reduced nightly ETL runtime
EDUCATION
Cascadia State University                           Sep 2016 – Jun 2020
Bachelor of Science in Computer Science
SKILLS
Languages: Python, SQL
"""
    result = parse_plain_text(text)
    p = result.profile
    assert p.contact.name == "Avery Quill" and p.contact.email == "avery.quill@example.com"
    e = p.experience[0]
    assert e.title == "Software Engineer" and e.employer == "Lanternfish Logistics" and e.dates == "Mar 2022 – Present"
    assert e.bullets[0].text.endswith("processes about 40,000 requests per day")  # wrapped line re-joined
    assert len(e.bullets) == 2
    assert p.education[0].institution == "Cascadia State University"
    assert p.skills[0].items == ["Python", "SQL"]
    assert "inferred from plain text" in result.warnings[0]


def test_pdf_text_extraction(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(text_pdf(["Avery Quill", "EXPERIENCE", "Software Engineer at Lanternfish Logistics"] * 6))
    result = extract_pdf_text(path)
    assert result.pages == 1
    assert "Lanternfish Logistics" in result.text
    assert not any("scan" in w for w in result.warnings)


def test_scanned_or_empty_pdf_is_detected(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    path = tmp_path / "blank.pdf"
    path.write_bytes(buf.getvalue())
    result = extract_pdf_text(path)
    assert result.pages == 1
    assert any("scan" in w for w in result.warnings)


def test_profile_validation_reports_missing_facts(profile):
    assert profile_issues(profile) == []
    broken = profile.model_copy(deep=True)
    broken.contact.email = "not-an-email"
    broken.experience[0].dates = ""
    issues = " ".join(profile_issues(broken))
    assert "does not look valid" in issues and "dates are missing" in issues
    assert "name is missing" in " ".join(profile_issues(ResumeProfile()))


def test_profile_ids_are_unique_and_repaired(profile):
    ids = [e.id for e in build_evidence(profile)]
    assert len(ids) == len(set(ids))
    dump = profile.model_dump()
    dump["experience"][1]["id"] = dump["experience"][0]["id"]  # duplicate
    dump["experience"][0]["bullets"][0]["id"] = "../../etc"  # hostile
    repaired = ResumeProfile.model_validate(dump)
    assert repaired.experience[0].id != repaired.experience[1].id
    assert repaired.experience[0].bullets[0].id.startswith("blt_")
