"""Optional live test against the real Groq API.

Runs only when GROQ_API_KEY is set (in the environment or backend/.env). It sends the fictional
sample resume and job description — never real data.
"""
import pytest

from app.ai.groq_client import GroqProvider
from app.ai.tailoring import generate_suggestions
from app.config import load_settings
from app.jd.analyzer import analyze_jd
from app.matching.matcher import build_match_report
from app.models import build_evidence

settings = load_settings()
pytestmark = pytest.mark.skipif(not settings.ai_configured, reason="GROQ_API_KEY is not configured; live Groq test skipped")


def test_live_groq_returns_schema_valid_grounded_suggestions(profile, sample_jd):
    analysis = analyze_jd(sample_jd)
    report = build_match_report(analysis.requirements, profile)
    suggestions, meta = generate_suggestions(GroqProvider(settings), profile=profile, requirements=analysis.requirements,
                                             report=report, jd_text=sample_jd, target_role=analysis.job_title)
    assert meta["model"] == settings.groq_model
    known = {e.id for e in build_evidence(profile)}
    for s in suggestions:
        assert s.status in ("pending", "invalid")
        if s.status == "pending":
            assert s.evidence_ids and set(s.evidence_ids) <= known
