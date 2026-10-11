"""LaTeX escaping, template rendering, compilation and PDF validation."""
import pytest

from app.ats.validate import squash, validate_pdf
from app.latex.compiler import compile_latex, detect_toolchain, sha256_text
from app.latex.escape import escape_latex, escape_url, normalise_url
from app.latex.renderer import build_view, render_latex
from app.models import ResumeConfig
from app.parsing.pdf_extract import extract_pdf_text

from .conftest import requires_latex


@pytest.mark.parametrize("raw,expected", [
    ("R&D", r"R\&D"),
    ("100%", r"100\%"),
    ("$5", r"\$5"),
    ("#1", r"\#1"),
    ("snake_case", r"snake\_case"),
    ("{x}", r"\{x\}"),
    (r"C:\temp", r"C:\textbackslash{}temp"),
    ("~home ^caret", r"\textasciitilde{}home \textasciicircum{}caret"),
    ("a < b > c | d", r"a \textless{} b \textgreater{} c \textbar{} d"),
    ("2020 – 2021 — now", "2020 -- 2021 --- now"),
    ("--verbose", "-{}-verbose"),
    ("line one\nline two\ttabbed", "line one line two tabbed"),
    ("“quoted” it’s", "``quoted'' it's"),
    ("zero\u200bwidth\x07bell", "zerowidthbell"),
])
def test_escape_latex(raw, expected):
    assert escape_latex(raw) == expected


def test_escaping_neutralises_injected_commands():
    hostile = r"\input{/etc/passwd} \write18{rm -rf ~} \end{document} %comment"
    out = escape_latex(hostile)
    assert "\\input" not in out and "\\write18" not in out and "\\end{document}" not in out
    assert out.startswith(r"\textbackslash{}input\{/etc/passwd\}")
    assert out.endswith(r"\%comment")


def test_multiline_keeps_paragraphs_only():
    assert escape_latex("one\ntwo\n\nthree & four", multiline=True) == "one two\n\nthree \\& four"


def test_urls_are_made_inert_or_dropped():
    assert normalise_url("github.com/x") == "https://github.com/x"
    assert normalise_url("a@b.co") == "mailto:a@b.co"
    assert normalise_url("javascript:alert(1)") == ""
    assert escape_url("file:///etc/passwd") == ""
    out = escape_url("https://ex.com/a_b?q=1&r=50%#frag}{\\x")
    assert out == r"https://ex.com/a\_b?q=1\&r=50\%\#frag\%7D\%7B\%5Cx"


def test_template_commands_are_not_escaped_but_data_is(profile):
    profile.experience[0].bullets[0].text = r"Saved 50% & \textbf{cost} #1_x"
    profile.contact.name = "Avery {Quill}"
    source, _view = render_latex(profile, ResumeConfig())
    assert r"\documentclass[11pt,letterpaper]{article}" in source
    assert r"\begin{itemize}" in source and r"\cvsection{Experience}" in source
    assert r"\item Saved 50\% \& \textbackslash{}textbf\{cost\} \#1\_x" in source
    assert r"{\LARGE\bfseries Avery \{Quill\}}" in source
    assert "\\VAR" not in source and "\\BLOCK" not in source
    assert source.count(r"\begin{document}") == 1 and source.rstrip().endswith(r"\end{document}")
    assert "shell" not in source.lower() and "write18" not in source


def test_config_controls_order_optional_sections_and_skill_priority(profile):
    config = ResumeConfig(section_order=["education", "experience"], include_summary=False, include_projects=False,
                          prioritized_skills=["sql", "Bash"], paper="a4", font_size=10)
    source, view = render_latex(profile, config)
    keys = [s.key for s in view.sections]
    assert keys[:2] == ["education", "experience"] and "summary" not in keys and "projects" not in keys
    assert "Trailhead Tracker" not in source and r"\documentclass[10pt,a4paper]" in source
    languages = next(items for cat, items in next(s for s in view.sections if s.key == "skills").groups if cat == "Languages")
    assert languages == ["SQL", "Bash", "Python", "TypeScript", "JavaScript"]  # reordered, nothing added or lost


def test_view_never_alters_content(profile):
    view = build_view(profile, ResumeConfig())
    printed = squash(" ".join(view.all_text()))
    for e in profile.experience:
        for value in (e.employer, e.title, e.dates, *[b.text for b in e.bullets]):
            assert squash(value) in printed


def test_preflight_reports_toolchain():
    tc = detect_toolchain()
    assert tc.can_compile == (tc.engine is not None)
    if not tc.can_compile:
        assert any(m["name"] == "LaTeX compiler" and "Termux" in m["install"] for m in tc.missing)


def test_compile_without_a_compiler_fails_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    tc = detect_toolchain()
    assert not tc.can_compile and {m["name"] for m in tc.missing} == {"LaTeX compiler", "pdftotext (Poppler)"}
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-stale")
    result = compile_latex(r"\documentclass{article}\begin{document}x\end{document}", tmp_path, toolchain=tc)
    assert not result.ok and "No LaTeX compiler" in result.error
    assert not (tmp_path / "resume.pdf").exists()  # a stale PDF must not survive a failed build


@requires_latex
def test_compile_success_and_pdf_matches_draft(tmp_path, profile):
    profile.experience[0].bullets[0].text += r" — 100% of C:\temp & {x}_y #1 $5 ~ ^ <a> --flag café"
    config = ResumeConfig(target_role="Backend Engineer")
    source, view = render_latex(profile, config)
    result = compile_latex(source, tmp_path)
    assert result.ok, result.error + "\n" + result.log_excerpt
    assert result.pdf_path == tmp_path / "resume.pdf" and result.pdf_path.read_bytes().startswith(b"%PDF-")
    assert result.tex_sha256 == sha256_text(source)
    assert list(tmp_path.iterdir()) == [result.pdf_path]  # build directory cleaned up

    text = extract_pdf_text(result.pdf_path, layout=False).text
    for expected in ("Avery Quill", "avery.quill@example.com", "Lanternfish Logistics", "Mar 2022", "Trailhead Tracker",
                     "customer_events", "30%", "service & cut", r"C:\temp", "{x}_y #1 $5", "--flag", "café"):
        assert expected in text, expected

    report = validate_pdf(result.pdf_path, view, config, compiled_sha=result.tex_sha256,
                          current_sha=sha256_text(source), engine=result.engine)
    status = {c["id"]: c["status"] for c in report["checks"]}
    assert report["ok"] and report["pages"] == 1
    for check in ("pdf_exists", "source_match", "page_count", "text_extraction", "headings", "contact", "employment",
                  "employment_dates", "projects", "approved_content", "unapproved_content", "reading_order",
                  "date_consistency"):
        assert status[check] == "pass", (check, next(c for c in report["checks"] if c["id"] == check))
    assert "cannot guarantee" in report["disclaimer"]

    # The validator must notice when the PDF does not correspond to the approved draft.
    tampered = profile.model_copy(deep=True)
    tampered.experience[0].bullets[1].text = "Reduced nightly ETL runtime by 99% single-handedly"
    tampered.experience[1].dates = "Jan 2015 – Feb 2022"
    _src, other_view = render_latex(tampered, config)
    bad = validate_pdf(result.pdf_path, other_view, ResumeConfig(max_pages=1), compiled_sha="different",
                       current_sha=sha256_text(source), engine=result.engine)
    bad_status = {c["id"]: c["status"] for c in bad["checks"]}
    assert not bad["ok"]
    assert bad_status["approved_content"] == "fail" and bad_status["employment_dates"] == "fail"
    assert bad_status["source_match"] == "fail" and bad_status["unapproved_content"] == "warn"


@requires_latex
def test_compile_failure_is_reported_and_leaves_no_pdf(tmp_path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-stale")
    result = compile_latex("\\documentclass{article}\n\\begin{document}\n\\thiscommanddoesnotexist\n\\end{document}\n", tmp_path)
    assert not result.ok and result.error and result.pdf_path is None
    assert "thiscommanddoesnotexist" in result.log_excerpt or "Undefined control sequence" in result.log_excerpt
    assert not (tmp_path / "resume.pdf").exists()


@requires_latex
def test_shell_escape_is_disabled(tmp_path):
    marker = tmp_path / "pwned.txt"
    source = ("\\documentclass{article}\n\\begin{document}\n"
              f"\\immediate\\write18{{touch {marker}}}\nok\n\\end{{document}}\n")
    compile_latex(source, tmp_path)
    assert not marker.exists()


def test_page_limit_is_a_warning_not_truncation(tmp_path, profile):
    from .conftest import text_pdf
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(text_pdf(["Avery Quill"] * 30))
    view = build_view(profile, ResumeConfig())
    report = validate_pdf(pdf, view, ResumeConfig(max_pages=1), compiled_sha="a", current_sha="a", engine=None)
    assert next(c for c in report["checks"] if c["id"] == "page_count")["status"] == "pass"
    assert next(c for c in report["checks"] if c["id"] == "approved_content")["status"] == "fail"
    missing = validate_pdf(tmp_path / "nope.pdf", view, ResumeConfig(), compiled_sha="a", current_sha="a", engine=None)
    assert not missing["ok"] and missing["checks"][0]["status"] == "fail"
