"""HTTP-level behaviour: uploads, file safety, the tailoring workflow, isolation, privacy."""
import hashlib
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.ai.provider import AIRateLimited
from app.main import create_app

from .conftest import FakeProvider, make_settings, requires_latex, text_pdf


def upload(client, name, data, mime="application/octet-stream"):
    return client.post("/api/resumes", files={"file": (name, data, mime)})


def start_session(client, resume, jd):
    sid = client.post("/api/sessions", json={"resume_id": resume["id"]}).json()["id"]
    r = client.put(f"/api/sessions/{sid}/jd", json={"jd_text": jd})
    assert r.status_code == 200, r.text
    return r.json()


def bullet(session, fragment):
    return next(e for e in session["evidence"] if fragment in e["text"] and e["kind"].endswith("bullet"))


def suggestion(target, text, evidence=None, **kw):
    return {"target_id": target, "proposed_text": text, "reason": "clearer", "requirement_ids": [],
            "evidence_ids": [target] if evidence is None else evidence, "confidence": "high", **kw}


def consent(client):
    assert client.put("/api/settings", json={"ai_consent": True}).json()["ai_consent"] is True


# ---------------------------------------------------------------- health / preflight


def test_health_and_system_without_api_key(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))  # real GroqProvider, no key
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/system").json()
    assert info["ai"]["configured"] is False and "GROQ_API_KEY" in info["ai"]["setup_hint"]
    assert info["ai"]["model"] == "openai/gpt-oss-120b" and info["ai"]["consent"] is False
    assert "Groq" in info["ai"]["privacy_notice"]
    assert info["server"]["local_only"] is True
    assert set(info["toolchain"]) >= {"engine", "can_compile", "missing", "pdftotext"}


def test_app_works_without_key_but_ai_endpoint_explains(tmp_path, sample_tex, sample_jd):
    client = TestClient(create_app(make_settings(tmp_path)))
    resume = upload(client, "cv.tex", sample_tex.encode()).json()
    session = start_session(client, resume, sample_jd)
    assert session["match"]["score"]["value"] > 0  # deterministic analysis works offline
    client.put("/api/settings", json={"ai_consent": True})
    r = client.post(f"/api/sessions/{session['id']}/suggestions/generate")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_not_configured"
    assert "GROQ_API_KEY" in r.json()["detail"]["message"]
    assert client.get(f"/api/sessions/{session['id']}").json()["suggestions"] == []  # nothing fabricated


# ---------------------------------------------------------------- uploads


def test_upload_tex_preserves_original_bytes(client, tmp_path, sample_tex):
    raw = sample_tex.encode()
    resume = upload(client, "my resume.tex", raw).json()
    assert resume["source_kind"] == "tex" and resume["version"] == 1 and resume["verified"] is False
    assert resume["profile"]["contact"]["name"] == "Avery Quill"
    assert "Lanternfish Logistics" in resume["extracted_text"] and resume["issues"] == []
    stored = tmp_path / "data" / "uploads" / resume["id"] / "original.tex"
    assert stored.read_bytes() == raw
    got = client.get(f"/api/resumes/{resume['id']}/original")
    assert got.content == raw and "attachment" in got.headers["content-disposition"]


def test_upload_pdf_is_parsed_and_flagged_for_review(client):
    pdf = text_pdf(["Avery Quill", "avery.quill@example.com", "EXPERIENCE",
                    "Software Engineer   Mar 2022 - Present", "Lanternfish Logistics",
                    "- Built a FastAPI service that validates shipment manifests for carriers every day",
                    "EDUCATION", "Cascadia State University   2016 - 2020", "Bachelor of Science"])
    r = upload(client, "cv.pdf", pdf, "application/pdf")
    assert r.status_code == 201, r.text
    resume = r.json()
    assert resume["source_kind"] == "pdf" and "Lanternfish Logistics" in resume["extracted_text"]
    assert resume["profile"]["contact"]["email"] == "avery.quill@example.com"
    assert any("inferred from plain text" in w for w in resume["warnings"])


def test_scanned_pdf_upload_warns(client):
    import io
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    resume = upload(client, "scan.pdf", buf.getvalue()).json()
    assert any("scan" in w for w in resume["warnings"])


@pytest.mark.parametrize("name,data,status,code", [
    ("cv.docx", b"PK\x03\x04", 415, "unsupported_type"),
    ("cv.exe", b"MZ", 415, "unsupported_type"),
    ("cv.tex.sh", b"#!/bin/sh", 415, "unsupported_type"),
    ("fake.pdf", b"this is not a pdf", 415, "invalid_file"),
    ("binary.tex", b"\\section{A}\x00\x01\x02", 415, "invalid_file"),
    ("empty.tex", b"   ", 400, "empty_file"),
    ("big.tex", b"a" * 200_001, 413, "too_large"),
    ("broken.pdf", b"%PDF-1.4\ngarbage", 422, "unreadable_pdf"),
])
def test_upload_validation(client, tmp_path, name, data, status, code):
    r = upload(client, name, data)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert client.get("/api/resumes").json() == []
    assert list((tmp_path / "data" / "uploads").iterdir()) == []  # nothing left behind


def test_client_filename_cannot_choose_the_storage_path(client, tmp_path, sample_tex):
    resume = upload(client, "../../../../tmp/evil.tex", sample_tex.encode()).json()
    assert resume["source_filename"] == "evil.tex"
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert sorted(files) == ["data/cvforge.sqlite3", f"data/uploads/{resume['id']}/original.tex"]


@pytest.mark.parametrize("bad", ["..", "..%2F..%2Fetc", "abc", "A" * 32, "0" * 31, "%2e%2e"])
def test_path_traversal_ids_are_rejected(client, bad):
    for url in (f"/api/resumes/{bad}", f"/api/resumes/{bad}/original", f"/api/sessions/{bad}",
                f"/api/sessions/{bad}/files/pdf"):
        assert client.get(url).status_code == 404
    assert client.delete(f"/api/sessions/{bad}").status_code in (404, 405)  # 405: path normalised away from the route
    unknown = "0" * 32
    assert client.get(f"/api/sessions/{unknown}/files/tex").status_code == 404
    assert client.get(f"/api/sessions/{unknown}/files/passwd").status_code == 422


# ---------------------------------------------------------------- master profile


def test_profile_edit_bumps_version_tracks_origin_and_keeps_original(client, tmp_path, resume):
    original = (tmp_path / "data" / "uploads" / resume["id"] / "original.tex").read_bytes()
    profile = resume["profile"]
    profile["experience"][0]["bullets"][0]["text"] = "Edited by the user"
    profile["experience"][0]["bullets"].append({"text": "Brand new bullet"})
    profile["summary"] = "New summary."
    r = client.put(f"/api/resumes/{resume['id']}", json={"profile": profile, "verified": True, "name": "Main CV"})
    updated = r.json()
    assert updated["version"] == 2 and updated["verified"] is True and updated["name"] == "Main CV"
    bullets = updated["profile"]["experience"][0]["bullets"]
    assert bullets[0]["origin"] == "user" and bullets[0]["source_line"] is None
    assert bullets[1]["origin"] == "document" and bullets[1]["source_line"]
    assert bullets[-1]["origin"] == "user" and bullets[-1]["id"].startswith("blt_")
    assert updated["profile"]["summary_origin"] == "user"
    assert updated["profile"]["experience"][1]["origin"] == "document"
    assert (tmp_path / "data" / "uploads" / resume["id"] / "original.tex").read_bytes() == original


def test_manual_profile_and_validation_errors_do_not_echo_content(client):
    manual = client.post("/api/resumes/manual", json={"name": "Typed in"}).json()
    assert manual["source_kind"] == "manual" and "Contact name is missing." in manual["issues"]
    r = client.put(f"/api/resumes/{manual['id']}", json={"profile": {"experience": "SECRET-VALUE"}, "verified": False})
    assert r.status_code == 422 and "SECRET-VALUE" not in r.text


# ---------------------------------------------------------------- workflow


def test_jd_analysis_and_requirement_editing(client, resume, sample_jd):
    session = start_session(client, resume, sample_jd)
    assert session["job_title"] == "Backend Software Engineer" and session["employer"] == "Northwind Freight Systems"
    assert session["resume_version"] == 1 and session["status"] == "analyzed"
    reqs = session["analysis"]["requirements"]
    go = next(r for r in reqs if r["text"] == "Knowledge of Go")
    statuses = {m["requirement_id"]: m["status"] for m in session["match"]["matches"]}
    assert statuses[go["id"]] == "unsupported"

    kept = [r for r in reqs if r["id"] != go["id"]]
    kept.append({"text": "Experience with shipment manifests", "category": "required_skill", "importance": "must",
                 "keywords": ["shipment manifests"]})
    r = client.put(f"/api/sessions/{session['id']}/requirements",
                   json={"job_title": "Platform Engineer", "employer": "", "requirements": kept})
    updated = r.json()
    assert updated["job_title"] == "Platform Engineer"
    added = next(r for r in updated["analysis"]["requirements"] if "manifests" in r["text"])
    assert added["origin"] == "user" and added["id"].startswith("req_")
    new_status = {m["requirement_id"]: m["status"] for m in updated["match"]["matches"]}
    assert new_status[added["id"]] == "supported" and go["id"] not in new_status
    assert client.put(f"/api/sessions/{session['id']}/jd", json={"jd_text": ""}).status_code == 422


def test_consent_is_required_before_any_ai_request(client, provider, resume, sample_jd):
    session = start_session(client, resume, sample_jd)
    r = client.post(f"/api/sessions/{session['id']}/suggestions/generate")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    assert provider.calls == []
    consent(client)
    assert client.get("/api/system").json()["ai"]["consent_at"]
    provider.queue.append({"suggestions": []})
    assert client.post(f"/api/sessions/{session['id']}/suggestions/generate").status_code == 200
    assert len(provider.calls) == 1
    client.put("/api/settings", json={"ai_consent": False})  # consent can be withdrawn
    assert client.post(f"/api/sessions/{session['id']}/suggestions/generate").status_code == 403


def test_ai_failures_surface_cleanly_and_change_nothing(client, provider, resume, sample_jd):
    consent(client)
    session = start_session(client, resume, sample_jd)
    provider.queue.append(AIRateLimited("Groq rate limit reached. Try again in about 8 seconds.", retry_after=7))
    r = client.post(f"/api/sessions/{session['id']}/suggestions/generate")
    assert r.status_code == 429
    assert r.json()["detail"] == {"code": "ai_rate_limited", "retry_after": 7,
                                  "message": "Groq rate limit reached. Try again in about 8 seconds."}
    provider.queue.append({"suggestions": [{"target_id": 5}]})
    r = client.post(f"/api/sessions/{session['id']}/suggestions/generate")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "ai_invalid_response"
    assert client.get(f"/api/sessions/{session['id']}").json()["suggestions"] == []


def test_review_flow_accept_reject_edit_confirm_reset(client, provider, resume, sample_jd):
    consent(client)
    session = start_session(client, resume, sample_jd)
    sid = session["id"]
    fastapi, docker, reviews, sql = (bullet(session, t) for t in ("FastAPI", "Docker", "code reviews", "SQL reports"))
    provider.queue.append({"suggestions": [
        suggestion(fastapi["id"], "Built a FastAPI service validating shipment manifests at about 40,000 requests per day"),
        suggestion(docker["id"], "Led migration of 12 services to Docker and Kubernetes on AWS ECS with a team of 5 engineers"),
        suggestion(reviews["id"], "Participated in code reviews and the on-call rotation for the customer_events pipeline"),
        suggestion(sql["id"], "Wrote SQL reports", evidence=["invented_id"]),
        suggestion(session["profile"]["experience"][0]["id"], "Principal Engineer"),
    ]})
    data = client.post(f"/api/sessions/{sid}/suggestions/generate").json()
    by_target = {s["target_id"]: s for s in data["suggestions"]}
    assert data["suggestion_counts"] == {"pending": 3, "accepted": 0, "modified": 0, "rejected": 0, "invalid": 2}
    assert data["draft"] == data["profile"]  # nothing enters the draft before approval

    def decide(target, **body):
        return client.post(f"/api/sessions/{sid}/suggestions/{by_target[target]['id']}/decision", json=body)

    # invalid suggestions can never be applied
    assert decide(sql["id"], action="accept").status_code == 409
    # clean suggestion: plain accept
    assert decide(fastapi["id"], action="accept").status_code == 200
    # flagged suggestion: needs explicit confirmation, and says why
    r = decide(docker["id"], action="accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required"
    flag_codes = {f["code"] for f in r.json()["detail"]["flags"]}
    assert {"unsupported_claim", "seniority_language"} <= flag_codes
    assert decide(docker["id"], action="reject").json()["suggestion_counts"]["rejected"] == 1
    # user edit introducing an unverifiable number also needs confirmation
    edit = "Participated in code reviews for the customer_events pipeline, reviewing 200 pull requests"
    r = decide(reviews["id"], action="edit", text=edit)
    assert r.status_code == 409 and "new_number" in {f["code"] for f in r.json()["detail"]["flags"]}
    data = decide(reviews["id"], action="edit", text=edit, confirm=True).json()
    edited = next(s for s in data["suggestions"] if s["target_id"] == reviews["id"])
    assert edited["status"] == "modified" and edited["confirmed"] is True and edited["final_text"] == edit

    draft_bullets = [b["text"] for e in data["draft"]["experience"] for b in e["bullets"]]
    assert by_target[fastapi["id"]]["proposed_text"] in draft_bullets and edit in draft_bullets
    assert docker["text"] in draft_bullets  # rejected -> original kept
    assert not any("Kubernetes" in b or "Principal" in json.dumps(data["draft"]) for b in draft_bullets)
    master_bullets = [b["text"] for e in data["profile"]["experience"] for b in e["bullets"]]
    assert fastapi["text"] in master_bullets  # snapshot of the master is untouched

    # another wording
    provider.queue.append({"suggestions": [suggestion(fastapi["id"], "Developed a FastAPI service that validates shipment manifests (about 40,000 requests per day)")]})
    data = client.post(f"/api/sessions/{sid}/suggestions/{by_target[fastapi['id']]['id']}/regenerate").json()
    again = next(s for s in data["suggestions"] if s["target_id"] == fastapi["id"])
    assert again["status"] == "pending" and again["proposed_text"].startswith("Developed") and len(again["history"]) == 1

    # reset restores the original master content
    data = client.post(f"/api/sessions/{sid}/suggestions/reset").json()
    assert data["draft"] == data["profile"]
    assert data["suggestion_counts"] == {"pending": 3, "accepted": 0, "modified": 0, "rejected": 0, "invalid": 2}


def test_sessions_are_isolated_and_master_is_never_modified(client, provider, resume, sample_jd, tmp_path):
    consent(client)
    before = client.get(f"/api/resumes/{resume['id']}").json()
    original = (tmp_path / "data" / "uploads" / resume["id"] / "original.tex").read_bytes()

    first = start_session(client, resume, sample_jd)
    target = bullet(first, "FastAPI")
    provider.queue.append({"suggestions": [suggestion(target["id"], "Built a FastAPI service for manifest validation (about 40,000 requests per day)")]})
    data = client.post(f"/api/sessions/{first['id']}/suggestions/generate").json()
    client.post(f"/api/sessions/{first['id']}/suggestions/{data['suggestions'][0]['id']}/decision", json={"action": "accept"})
    client.put(f"/api/sessions/{first['id']}/config", json={"target_role": "Role A", "include_projects": False})

    second = start_session(client, resume, "Data Analyst\nRequirements\n- SQL and Tableau")
    assert second["suggestions"] == [] and second["config"]["include_projects"] is True
    assert second["draft"] == second["profile"] == before["profile"]
    assert second["job_title"] == "Data Analyst"

    after = client.get(f"/api/resumes/{resume['id']}").json()
    assert after["profile"] == before["profile"] and after["version"] == before["version"]
    assert (tmp_path / "data" / "uploads" / resume["id"] / "original.tex").read_bytes() == original

    # editing the master later does not rewrite an existing session's snapshot
    profile = after["profile"]
    profile["summary"] = "Changed later."
    client.put(f"/api/resumes/{resume['id']}", json={"profile": profile, "verified": True})
    assert client.get(f"/api/sessions/{first['id']}").json()["profile"]["summary"] == before["profile"]["summary"]
    third = client.post("/api/sessions", json={"resume_id": resume["id"]}).json()
    assert third["profile"]["summary"] == "Changed later." and third["resume_version"] == 2

    listing = client.get("/api/sessions").json()
    assert {s["id"] for s in listing} == {first["id"], second["id"], third["id"]}
    assert client.get("/api/system").json()["counts"]["sessions"] == 3


def test_generate_source_without_compiler_keeps_tex_and_reports_honestly(client, resume, sample_jd, monkeypatch):
    session = start_session(client, resume, sample_jd)
    sid = session["id"]
    assert client.post(f"/api/sessions/{sid}/compile").status_code == 409  # nothing generated yet
    data = client.post(f"/api/sessions/{sid}/generate").json()
    assert data["status"] == "generated" and data["generated"]["stale"] is False
    assert data["tex"].startswith("% Generated by CV Forge") and "Lanternfish Logistics" in data["tex"]
    tex = client.get(f"/api/sessions/{sid}/files/tex")
    assert tex.text == data["tex"] and 'filename="avery-quill-backend-software-engineer.tex"' in tex.headers["content-disposition"]
    assert hashlib.sha256(tex.content).hexdigest() == data["generated"]["tex_sha256"]

    monkeypatch.setattr("shutil.which", lambda name: None)
    data = client.post(f"/api/sessions/{sid}/compile").json()
    assert data["compile"]["ok"] is False and "No LaTeX compiler" in data["compile"]["error"]
    assert data["has_pdf"] is False and data["validation"] is None and data["status"] == "generated"
    assert client.get(f"/api/sessions/{sid}/files/pdf").status_code == 404
    assert client.get(f"/api/sessions/{sid}/files/tex").status_code == 200  # source survives a failed build

    # changing the draft afterwards marks the source stale and blocks compiling the outdated file
    data = client.put(f"/api/sessions/{sid}/config", json={"include_summary": False}).json()
    assert data["generated"]["stale"] is True
    assert client.post(f"/api/sessions/{sid}/compile").json()["detail"]["code"] == "stale_source"


@requires_latex
def test_full_workflow_compile_validate_and_download(client, provider, resume, sample_jd):
    consent(client)
    session = start_session(client, resume, sample_jd)
    sid = session["id"]
    target = bullet(session, "FastAPI")
    approved = "Built a FastAPI service validating shipment manifests, handling about 40,000 requests per day"
    provider.queue.append({"suggestions": [suggestion(target["id"], approved),
                                           suggestion(bullet(session, "Docker")["id"], "Solely migrated 12 services to Docker on AWS ECS")]})
    data = client.post(f"/api/sessions/{sid}/suggestions/generate").json()
    accept, leave_pending = data["suggestions"]
    client.post(f"/api/sessions/{sid}/suggestions/{accept['id']}/decision", json={"action": "accept"})
    client.put(f"/api/sessions/{sid}/config", json={"target_role": "Backend Engineer", "prioritized_skills": ["SQL"],
                                                    "section_order": ["summary", "experience", "skills"]})
    data = client.post(f"/api/sessions/{sid}/generate").json()
    assert approved in data["tex"] and "Solely" not in data["tex"]  # pending suggestion is not in the source
    data = client.post(f"/api/sessions/{sid}/compile").json()
    assert data["compile"]["ok"] is True, data["compile"]
    assert data["status"] == "compiled" and data["has_pdf"] is True
    assert data["compile"]["tex_sha256"] == data["generated"]["tex_sha256"]

    formatting = data["validation"]["formatting"]
    assert formatting["ok"] and formatting["pages"] == 1
    assert approved.replace(" ", "") in formatting["extracted_text"].replace("\n", "").replace(" ", "")
    assert all(c["status"] in ("pass", "info") for c in formatting["checks"]), [c for c in formatting["checks"] if c["status"] not in ("pass", "info")]
    qual = data["validation"]["qualification"]
    assert {g["text"] for g in qual["gaps"]} == {"Experience with Kubernetes and Terraform",
                                                 "Familiarity with Kafka or other event streaming platforms",
                                                 "Knowledge of Go"}
    assert "Kubernetes" in qual["terminology"]["not_documented"] and "PostgreSQL" in qual["terminology"]["present"]
    assert qual["score"]["label"].startswith("Heuristic estimate")

    pdf = client.get(f"/api/sessions/{sid}/files/pdf")
    assert pdf.content.startswith(b"%PDF-") and pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("attachment") and pdf.headers["cache-control"] == "no-store"
    assert client.get(f"/api/sessions/{sid}/files/pdf?inline=1").headers["content-disposition"].startswith("inline")
    md = client.get(f"/api/sessions/{sid}/files/report.md").text
    assert md.startswith("# Match report — Backend Software Engineer") and "Not supported by the current resume" in md
    assert "Knowledge of Go" in md and "## Approved changes" in md and approved in md
    report = client.get(f"/api/sessions/{sid}/files/report.json").json()
    assert report["job_description"] == sample_jd and report["session"]["resume_version"] == 1
    assert report["validation"]["formatting"]["tex_sha256"] == data["generated"]["tex_sha256"]

    # regenerating removes the PDF that no longer matches
    client.put(f"/api/sessions/{sid}/config", json={"target_role": "Backend Engineer", "font_size": 10})
    data = client.post(f"/api/sessions/{sid}/generate").json()
    assert data["has_pdf"] is False and data["compile"] is None
    assert client.get(f"/api/sessions/{sid}/files/pdf").status_code == 404


# ---------------------------------------------------------------- privacy / deletion / access


def test_delete_removes_documents_and_metadata(client, tmp_path, resume, sample_jd):
    session = start_session(client, resume, sample_jd)
    client.post(f"/api/sessions/{session['id']}/generate")
    session_dir = tmp_path / "data" / "sessions" / session["id"]
    assert (session_dir / "resume.tex").is_file()
    assert client.delete(f"/api/sessions/{session['id']}").json() == {"deleted": True}
    assert not session_dir.exists() and client.get(f"/api/sessions/{session['id']}").status_code == 404
    assert client.delete(f"/api/resumes/{resume['id']}").json() == {"deleted": True}
    assert not (tmp_path / "data" / "uploads" / resume["id"]).exists()
    assert client.get("/api/resumes").json() == [] and client.delete(f"/api/resumes/{resume['id']}").status_code == 404


def test_retention_purges_old_sessions_but_never_master_resumes(client, tmp_path, resume, sample_jd):
    import sqlite3
    old = start_session(client, resume, sample_jd)
    fresh = start_session(client, resume, sample_jd)
    with sqlite3.connect(tmp_path / "data" / "cvforge.sqlite3") as db:
        db.execute("UPDATE sessions SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (old["id"],))
    assert client.post("/api/settings/purge").json() == {"purged_sessions": 0}  # disabled by default
    r = client.put("/api/settings", json={"retention_days": 30}).json()
    assert r["retention_days"] == 30 and r["purged_sessions"] == 1
    assert [s["id"] for s in client.get("/api/sessions").json()] == [fresh["id"]]
    assert len(client.get("/api/resumes").json()) == 1


def test_access_token_protects_the_api(tmp_path, sample_tex):
    client = TestClient(create_app(make_settings(tmp_path, access_token="s3cret-token"), provider=FakeProvider()))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/resumes").status_code == 401
    assert client.get("/api/resumes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = {"Authorization": "Bearer s3cret-token"}
    assert client.get("/api/resumes", headers=ok).status_code == 200
    assert client.post("/api/resumes", files={"file": ("a.tex", sample_tex.encode())}).status_code == 401


def test_logs_contain_no_resume_or_jd_content(client, provider, resume, sample_jd, caplog):
    caplog.set_level(logging.DEBUG)
    consent(client)
    session = start_session(client, resume, sample_jd)
    provider.queue.append({"suggestions": []})
    client.post(f"/api/sessions/{session['id']}/suggestions/generate")
    client.post(f"/api/sessions/{session['id']}/generate")
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("cvforge"))
    assert "session=" in logged
    for private in ("Avery", "Quill", "Lanternfish", "example.com", "Northwind", "shipment", "555-0142"):
        assert private not in logged


def test_built_frontend_never_shadows_api_or_escapes_its_folder(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app shell</html>")
    (tmp_path / "secret.txt").write_text("outside dist")
    monkeypatch.setattr("app.main.FRONTEND_DIST", dist)
    client = TestClient(create_app(make_settings(tmp_path), provider=FakeProvider()))
    assert "app shell" in client.get("/history").text  # client-side routes get the shell
    for path in ("/api", "/api/", "/api/nope", "/api/resumes/.."):
        r = client.get(path)
        assert r.status_code == 404 and "app shell" not in r.text
    assert "outside dist" not in client.get("/..%2Fsecret.txt").text
    assert "outside dist" not in client.get("/%2e%2e/secret.txt").text
