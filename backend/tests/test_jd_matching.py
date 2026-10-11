"""JD requirement extraction and requirement-to-evidence matching."""
from datetime import date

from app.jd.analyzer import analyze_jd
from app.lexicon import find_terms, term_in_text
from app.matching.matcher import build_match_report, estimate_years
from app.models import Requirement


def by_text(analysis, fragment):
    return next(r for r in analysis.requirements if fragment in r.text)


def test_title_employer_and_categories_are_extracted(sample_jd):
    a = analyze_jd(sample_jd)
    assert a.job_title == "Backend Software Engineer"
    assert a.employer == "Northwind Freight Systems"
    assert by_text(a, "3+ years").category == "experience" and by_text(a, "3+ years").importance == "must"
    assert by_text(a, "Python and SQL").category == "required_skill"
    assert by_text(a, "Python and SQL").keywords == ["Python", "SQL"]
    assert by_text(a, "Kubernetes").category == "preferred_skill" and by_text(a, "Kubernetes").importance == "nice"
    assert by_text(a, "REST APIs").category == "responsibility"
    assert by_text(a, "Bachelor").category == "qualification"
    texts = " ".join(r.text for r in a.requirements)
    assert "Health insurance" not in texts  # benefits are not requirements
    assert "small platform team" not in texts  # nor is the intro blurb


def test_unstructured_jd_falls_back_to_sentences():
    a = analyze_jd("Senior Data Engineer at Fernhill\nWe need someone with 5 years of experience who knows "
                   "Spark and Airflow. You enjoy long walks. A degree in a related field is preferred.")
    assert a.job_title == "Senior Data Engineer" and a.employer == "Fernhill"
    assert any("Spark" in r.keywords for r in a.requirements)
    assert not any("long walks" in r.text for r in a.requirements)
    assert any("No standard headings" in n for n in a.notes)


def test_lexicon_matching_respects_word_boundaries_and_aliases():
    assert find_terms("We use Postgres, k8s and React.js") == ["PostgreSQL", "Kubernetes", "React"]
    assert not term_in_text("Go", "We go to market quickly")
    assert term_in_text("Go", "Services written in Go and Rust")
    assert not term_in_text("Java", "JavaScript only")
    assert not term_in_text("C", "C++ and C# experience")
    assert term_in_text("C++", "Modern C++ (17/20)")
    assert not term_in_text("R", "R&D team")


def test_match_statuses_distinguish_demonstrated_claimed_and_missing(sample_jd, profile):
    a = analyze_jd(sample_jd)
    report = build_match_report(a.requirements, profile, today=date(2026, 1, 1))
    status = {by_id.requirement_id: by_id for by_id in report.matches}

    docker = status[by_text(a, "Docker on AWS").id]
    assert docker.status == "supported"
    assert any("Docker containers on AWS ECS" in e.excerpt and e.strength == "demonstrated" for e in docker.evidence)

    # Python is in the skills list and summary but in no bullet: a keyword hit alone is not proof.
    python = status[by_text(a, "Python and SQL").id]
    assert python.status == "needs_confirmation"
    assert "Python" in python.note

    cicd = status[by_text(a, "CI/CD").id]
    assert cicd.status == "indirect"  # GitHub Actions / pytest are related, not the same claim

    for fragment in ("Kubernetes", "Kafka", "Knowledge of Go"):
        m = status[by_text(a, fragment).id]
        assert m.status == "unsupported" and m.evidence == []

    years = status[by_text(a, "3+ years").id]
    assert years.status == "needs_confirmation" and "roughly" in years.note


def test_score_is_labelled_estimate_and_gaps_lower_it(sample_jd, profile):
    a = analyze_jd(sample_jd)
    report = build_match_report(a.requirements, profile)
    assert 0 < report.score.value < 100
    assert "estimate" in report.score.label.lower()
    assert "not an ATS score" in report.score.explanation
    assert report.score.counts["unsupported"] == 3
    only_gaps = [Requirement(id="r1", text="Knowledge of Go", keywords=["Go"], importance="must")]
    assert build_match_report(only_gaps, profile).score.value == 0


def test_user_supplied_keyword_outside_lexicon_is_matched_literally(profile):
    req = Requirement(id="r1", text="Experience with shipment manifests", keywords=["shipment manifests"])
    m = build_match_report([req], profile).matches[0]
    assert m.status == "supported" and "validates shipment manifests" in m.evidence[0].excerpt
    req = Requirement(id="r2", text="Experience with customs brokerage", keywords=["customs brokerage"])
    assert build_match_report([req], profile).matches[0].status == "unsupported"


def test_vague_requirement_is_unclear_not_claimed(profile):
    req = Requirement(id="r1", text="Great attitude", keywords=[])
    assert build_match_report([req], profile).matches[0].status == "unclear"


def test_years_estimate_merges_overlaps(profile):
    assert estimate_years(profile, today=date(2025, 6, 30)) == 5.0  # Jul 2020 .. Jun 2025 inclusive = 60 months
    profile.experience[0].dates = "sometime"
    profile.experience[1].dates = ""
    assert estimate_years(profile) is None
