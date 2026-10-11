"""Groq client behaviour (mocked HTTP), response schema validation and fact checks."""
import json

import httpx
import pytest
from pydantic import ValidationError

from app.ai.groq_client import GroqProvider
from app.ai.provider import (
    AIAuthError, AIInvalidResponse, AINotConfigured, AIQuotaExceeded, AIRateLimited, AIRequestError,
    AITimeout, AIUnavailable,
)
from app.ai.schemas import SUGGESTION_BATCH_SCHEMA, AISuggestion, AISuggestionBatch
from app.ai.tailoring import build_payload, generate_suggestions, regenerate_suggestion
from app.ai.validation import apply_suggestions, check_text, find_targets, validate_ai_suggestion
from app.config import Settings
from app.jd.analyzer import analyze_jd
from app.matching.matcher import build_match_report
from app.models import build_evidence, profile_corpus

from .conftest import FakeProvider

KEY = "gsk_test_SECRET_VALUE_123"
SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def groq(handler, **overrides):
    settings = Settings(groq_api_key=KEY, **overrides)
    slept: list[float] = []
    provider = GroqProvider(settings, transport=httpx.MockTransport(handler), sleep=slept.append)
    return provider, slept


def ok_response(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def call(provider):
    return provider.complete_json(system="sys", user="user", schema_name="n", json_schema=SCHEMA)


# ---------------------------------------------------------------- Groq client


def test_missing_api_key_never_calls_the_network():
    def handler(request):  # pragma: no cover - must not run
        raise AssertionError("network was called without an API key")

    provider = GroqProvider(Settings(groq_api_key=""), transport=httpx.MockTransport(handler))
    assert not provider.is_configured()
    with pytest.raises(AINotConfigured) as exc:
        call(provider)
    assert "GROQ_API_KEY" in exc.value.message


def test_strict_json_schema_request_shape():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return ok_response('{"suggestions": []}')

    provider, _ = groq(handler)
    assert call(provider) == {"suggestions": []}
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"] == {"type": "json_schema",
                                       "json_schema": {"name": "n", "strict": True, "schema": SCHEMA}}
    assert "stream" not in body and "tools" not in body  # not combinable with structured outputs


def test_models_without_strict_support_use_json_object_mode():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok_response("{}")

    provider, _ = groq(handler, groq_model="llama-3.3-70b-versatile")
    call(provider)
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen["body"]["messages"][0]["content"]


def test_model_is_configurable_in_one_place():
    provider, _ = groq(lambda r: ok_response("{}"), groq_model="openai/gpt-oss-20b")
    assert provider.model == "openai/gpt-oss-20b"
    assert provider.build_payload("s", "u", "n", SCHEMA)["model"] == "openai/gpt-oss-20b"


def test_invalid_key_is_reported_without_leaking_it():
    provider, slept = groq(lambda r: httpx.Response(401, json={"error": {"message": f"Invalid API Key {KEY}"}}))
    with pytest.raises(AIAuthError) as exc:
        call(provider)
    assert KEY not in exc.value.message and KEY not in str(exc.value)
    assert slept == []  # not retried


def test_rate_limit_is_surfaced_and_never_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "Rate limit reached for model"}})

    provider, slept = groq(handler, groq_max_retries=3)
    with pytest.raises(AIRateLimited) as exc:
        call(provider)
    assert exc.value.retry_after == 7 and "8 seconds" in exc.value.message
    assert len(calls) == 1 and slept == []


def test_quota_exhaustion_is_distinguished_from_rate_limiting():
    provider, _ = groq(lambda r: httpx.Response(429, json={"error": {"message": "You exceeded your current quota, check billing"}}))
    with pytest.raises(AIQuotaExceeded):
        call(provider)


def test_server_errors_are_retried_a_bounded_number_of_times():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="overloaded")

    provider, slept = groq(handler, groq_max_retries=2)
    with pytest.raises(AIUnavailable):
        call(provider)
    assert len(calls) == 3 and len(slept) == 2  # 1 try + 2 retries, then give up


def test_transient_failure_then_success():
    responses = [httpx.Response(500), ok_response('{"a": 1}')]
    provider, _ = groq(lambda r: responses.pop(0), groq_max_retries=1)
    assert call(provider) == {"a": 1}


def test_timeout_is_reported():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, _ = groq(handler, groq_max_retries=0)
    with pytest.raises(AITimeout):
        call(provider)


def test_network_failure_is_reported():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    provider, _ = groq(handler, groq_max_retries=0)
    with pytest.raises(AIUnavailable):
        call(provider)


@pytest.mark.parametrize("response", [
    ok_response("this is not json"),
    ok_response("[1, 2]"),
    ok_response(""),
    ok_response('{"suggestions": [', finish="length"),
    httpx.Response(200, json={"unexpected": True}),
    httpx.Response(400, json={"error": {"message": "Generated JSON does not match the expected schema."}}),
])
def test_malformed_model_output_raises_instead_of_being_guessed(response):
    provider, _ = groq(lambda r: response)
    with pytest.raises(AIInvalidResponse):
        call(provider)


def test_unknown_model_gives_actionable_error():
    provider, _ = groq(lambda r: httpx.Response(404, json={"error": {"message": "model not found"}}))
    with pytest.raises(AIRequestError) as exc:
        call(provider)
    assert "GROQ_MODEL" in exc.value.message


# ---------------------------------------------------------------- schema


def test_schema_is_strict_mode_compatible():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
            for child in node["properties"].values():
                walk(child)
        elif node.get("type") == "array":
            walk(node["items"])

    walk(SUGGESTION_BATCH_SCHEMA)


def raw(**kw):
    base = dict(target_id="x", proposed_text="text", reason="r", requirement_ids=[], evidence_ids=[], confidence="high")
    return {**base, **kw}


def test_pydantic_rejects_wrong_shapes():
    AISuggestionBatch.model_validate({"suggestions": [raw()]})
    for bad in ({"suggestions": [raw(confidence="certain")]}, {"suggestions": [raw(extra_field=1)]},
                {"suggestions": [{k: v for k, v in raw().items() if k != "evidence_ids"}]},
                {"suggestions": [raw(proposed_text="")]}, {"suggestions": "nope"}, {}):
        with pytest.raises(ValidationError):
            AISuggestionBatch.model_validate(bad)


# ---------------------------------------------------------------- deterministic validation


@pytest.fixture()
def ctx(profile, sample_jd):
    analysis = analyze_jd(sample_jd)
    report = build_match_report(analysis.requirements, profile)
    bullets = {b.text: b for e in profile.experience for b in e.bullets}
    return dict(profile=profile, analysis=analysis, report=report, jd=sample_jd,
                fastapi=next(b for t, b in bullets.items() if "FastAPI" in t),
                docker=next(b for t, b in bullets.items() if "Docker" in t),
                reviews=next(b for t, b in bullets.items() if "code reviews" in t))


def validate(ctx, **kw):
    return validate_ai_suggestion(AISuggestion(**raw(**kw)), profile=ctx["profile"],
                                  requirements=ctx["analysis"].requirements, jd_text=ctx["jd"],
                                  unsupported_requirement_ids={m.requirement_id for m in ctx["report"].matches
                                                               if m.status == "unsupported"})


def codes(sug):
    return {f.code for f in sug.flags}


def test_faithful_rewrite_passes_without_confirmation(ctx):
    b = ctx["fastapi"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Built a FastAPI service validating shipment manifests at about 40,000 requests per day")
    assert sug.status == "pending" and not sug.requires_confirmation and sug.flags == []
    assert sug.original_text == b.text  # original comes from the profile, never from the model
    assert sug.id.startswith("sug_")


def test_suggestion_without_valid_evidence_is_rejected(ctx):
    b = ctx["fastapi"]
    none = validate(ctx, target_id=b.id, evidence_ids=[], proposed_text="Something else entirely")
    fake = validate(ctx, target_id=b.id, evidence_ids=["blt_doesnotexist", "made_up"], proposed_text="Something else")
    for sug in (none, fake):
        assert sug.status == "invalid" and "evidence" in sug.invalid_reason
    assert "blt_doesnotexist" in fake.invalid_reason


def test_unknown_evidence_ids_are_dropped_and_flagged(ctx):
    b = ctx["fastapi"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id, "ghost_id"],
                   proposed_text="Built a FastAPI service that validates shipment manifests")
    assert sug.evidence_ids == [b.id]
    assert "unknown_evidence_id" in codes(sug) and sug.requires_confirmation


def test_protected_fields_are_not_ai_targets(ctx):
    profile = ctx["profile"]
    targets = find_targets(profile)
    for protected in (profile.experience[0].id, profile.education[0].id, profile.certifications[0].id,
                      profile.projects[0].id):
        assert protected not in targets
        sug = validate(ctx, target_id=protected, evidence_ids=[protected], proposed_text="Senior Staff Engineer")
        assert sug.status == "invalid" and "Protected fields" in sug.invalid_reason


def test_fabricated_metric_is_blocked(ctx):
    b = ctx["reviews"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Participated in code reviews and on-call rotation, cutting incidents by 45%")
    flag = next(f for f in sug.flags if f.code == "new_number")
    assert flag.severity == "blocker" and flag.terms == ["45"] and sug.requires_confirmation


def test_technology_not_in_resume_is_blocked(ctx):
    b = ctx["docker"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Worked with a team of 5 engineers to migrate 12 services to Docker containers on "
                                 "AWS ECS, orchestrated with Kubernetes and Terraform")
    flag = next(f for f in sug.flags if f.code == "unsupported_claim")
    assert flag.severity == "blocker" and set(flag.terms) == {"Kubernetes", "Terraform"}


def test_skill_borrowed_from_elsewhere_in_resume_needs_confirmation(ctx):
    b = ctx["reviews"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Participated in code reviews and on-call rotation for the customer_events Docker pipeline")
    assert "term_from_elsewhere" in codes(sug) and "unsupported_claim" not in codes(sug)


def test_seniority_inflation_and_team_to_individual_are_flagged(ctx):
    b = ctx["docker"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Led the migration of 12 services to Docker containers on AWS ECS")
    assert {"seniority_language", "team_to_individual"} <= codes(sug)
    assert "5" in next(f for f in sug.flags if f.code == "number_removed").terms


def test_unfamiliar_names_and_jd_copying_are_flagged(ctx):
    b = ctx["fastapi"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id],
                   proposed_text="Built a FastAPI service for Northwind to design and build REST APIs in Python for "
                                 "shipment tracking and billing")
    assert "Northwind" in next(f for f in sug.flags if f.code == "unfamiliar_term").terms
    assert "copied_from_jd" in codes(sug)


def test_skills_group_may_be_reordered_but_not_extended(ctx):
    group = ctx["profile"].skills[0]
    reorder = validate(ctx, target_id=group.id, evidence_ids=[group.id],
                       proposed_text="SQL, Python, Bash, TypeScript, JavaScript")
    assert reorder.status == "pending" and reorder.flags == [] and reorder.target_kind == "skills"
    extended = validate(ctx, target_id=group.id, evidence_ids=[group.id],
                        proposed_text="Go, Python, SQL, TypeScript, JavaScript, Bash")
    flag = next(f for f in extended.flags if f.code == "skill_not_in_resume")
    assert flag.severity == "blocker" and flag.terms == ["Go"]


def test_suggestion_tied_to_a_gap_requirement_is_flagged(ctx):
    gap = next(r for r in ctx["analysis"].requirements if "Kubernetes" in r.text)
    b = ctx["docker"]
    sug = validate(ctx, target_id=b.id, evidence_ids=[b.id], requirement_ids=[gap.id, "req_bogus"],
                   proposed_text="Worked with a team of 5 engineers migrating 12 services to Docker containers on AWS ECS")
    assert sug.requirement_ids == [gap.id]
    assert {"targets_gap", "unknown_requirement_id"} <= codes(sug)


def test_identical_text_is_not_a_suggestion(ctx):
    b = ctx["fastapi"]
    assert validate(ctx, target_id=b.id, evidence_ids=[b.id], proposed_text=b.text).status == "invalid"


def test_only_approved_and_confirmed_changes_reach_the_draft(ctx):
    profile = ctx["profile"]
    b1, b2, b3 = ctx["fastapi"], ctx["docker"], ctx["reviews"]
    accepted = validate(ctx, target_id=b1.id, evidence_ids=[b1.id], proposed_text="Built a FastAPI manifest validation service handling about 40,000 requests per day")
    assert not accepted.requires_confirmation
    accepted.status = "accepted"
    pending = validate(ctx, target_id=b2.id, evidence_ids=[b2.id], proposed_text="Worked with a team to migrate services")
    flagged = validate(ctx, target_id=b3.id, evidence_ids=[b3.id], proposed_text="Participated in code reviews, saving 99 hours")
    flagged.status = "accepted"  # accepted but never confirmed -> must not apply
    draft = apply_suggestions(profile, [accepted, pending, flagged])
    texts = [b.text for e in draft.experience for b in e.bullets]
    assert "Built a FastAPI manifest validation service handling about 40,000 requests per day" in texts
    assert b2.text in texts and b3.text in texts
    assert not any("99 hours" in t for t in texts)
    # the master object itself is untouched, and protected facts are identical in the draft
    assert b1.text.startswith("Built a FastAPI service that validates")
    for before, after in zip(profile.experience, draft.experience):
        assert (before.employer, before.title, before.dates) == (after.employer, after.title, after.dates)
    assert draft.education == profile.education and draft.certifications == profile.certifications


def test_check_text_on_new_summary_requires_review(profile):
    flags = check_text(kind="summary", original="", proposed="Engineer with Python experience.", cited=[],
                       corpus=profile_corpus(profile), jd_keywords=[], jd_text="")
    assert {f.code for f in flags} == {"term_from_elsewhere", "new_content"}


# ---------------------------------------------------------------- prompt + orchestration


def test_prompt_payload_is_focused_and_excludes_contact_details(ctx):
    payload = build_payload(ctx["profile"], ctx["analysis"].requirements, ctx["report"], "Backend Engineer")
    blob = json.dumps(payload)
    for private in ("avery.quill@example.com", "555-0142", "linkedin.com", "Avery Quill"):
        assert private not in blob
    ids = {i["id"] for i in payload["resume_items"]}
    assert ids <= {e.id for e in build_evidence(ctx["profile"])} | {"summary"}
    gaps = [r for r in payload["requirements"] if r["gap"]]
    assert {r["status"] for r in gaps} == {"unsupported"} and len(gaps) == 3
    editable = [i for i in payload["resume_items"] if i["editable"]]
    assert all(i["type"] in ("summary", "skill", "experience_bullet", "project_bullet") for i in editable)


def test_generate_validates_every_item_and_flags_duplicates(ctx):
    b = ctx["fastapi"]
    provider = FakeProvider()
    provider.queue.append({"suggestions": [
        raw(target_id=b.id, evidence_ids=[b.id], proposed_text="Built a FastAPI service validating shipment manifests"),
        raw(target_id=b.id, evidence_ids=[b.id], proposed_text="Built a second variant of the FastAPI service"),
        raw(target_id="nope", evidence_ids=[b.id], proposed_text="x"),
        raw(target_id=ctx["docker"].id, evidence_ids=[], proposed_text="Unsupported rewrite"),
    ]})
    suggestions, meta = generate_suggestions(provider, profile=ctx["profile"], requirements=ctx["analysis"].requirements,
                                             report=ctx["report"], jd_text=ctx["jd"], target_role="Backend Engineer")
    assert [s.status for s in suggestions] == ["pending", "invalid", "invalid", "invalid"]
    assert meta["model"] == "fake-model" and meta["resume_items_sent"] > 0


def test_schema_violating_answer_is_an_error_not_a_guess(ctx):
    provider = FakeProvider()
    provider.queue.append({"suggestions": [{"target_id": "x"}]})
    with pytest.raises(AIInvalidResponse):
        generate_suggestions(provider, profile=ctx["profile"], requirements=ctx["analysis"].requirements,
                             report=ctx["report"], jd_text=ctx["jd"], target_role="")


def test_regenerate_sends_previous_wordings_and_keeps_the_id(ctx):
    b = ctx["fastapi"]
    first = validate(ctx, target_id=b.id, evidence_ids=[b.id], proposed_text="Built a FastAPI service validating manifests")
    provider = FakeProvider()
    provider.queue.append({"suggestions": [raw(target_id=b.id, evidence_ids=[b.id],
                                               proposed_text="Developed a FastAPI service to validate shipment manifests")]})
    fresh = regenerate_suggestion(provider, first, profile=ctx["profile"], requirements=ctx["analysis"].requirements,
                                  report=ctx["report"], jd_text=ctx["jd"], target_role="")
    sent = json.loads(provider.calls[0]["user"])
    assert sent["previous_wordings"] == ["Built a FastAPI service validating manifests"]
    assert [i["id"] for i in sent["resume_items"] if i["editable"]] == [b.id]
    assert fresh.id == first.id and fresh.history == ["Built a FastAPI service validating manifests"]
    assert fresh.proposed_text.startswith("Developed")
