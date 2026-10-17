"""Idle shutdown for on-demand hosting (CVFORGE_IDLE_SHUTDOWN_MINUTES)."""
import asyncio
import signal

from fastapi.testclient import TestClient

from app import main
from app.main import create_app

from .conftest import FakeProvider, make_settings


def test_health_checks_do_not_count_as_activity(tmp_path):
    app = create_app(make_settings(tmp_path), provider=FakeProvider())
    client = TestClient(app)
    app.state.last_activity = 0.0
    assert client.get("/api/health").status_code == 200
    assert app.state.last_activity == 0.0
    assert client.get("/api/system").status_code == 200
    assert app.state.last_activity > 0.0
    assert app.state.in_flight == 0


def test_rejected_requests_still_count(tmp_path):
    app = create_app(make_settings(tmp_path, access_token="secret"), provider=FakeProvider())
    app.state.last_activity = 0.0
    assert TestClient(app).get("/api/system").status_code == 401
    assert app.state.last_activity > 0.0


def test_watcher_stops_the_server_once_idle(tmp_path, monkeypatch):
    app = create_app(make_settings(tmp_path), provider=FakeProvider())
    kills = []
    monkeypatch.setattr(main.os, "kill", lambda pid, sig: kills.append(sig))
    app.state.last_activity = -10_000.0
    asyncio.run(asyncio.wait_for(main._idle_watch(app, 0.05), timeout=2))
    assert kills == [signal.SIGTERM]


def test_watcher_waits_for_in_flight_requests(tmp_path, monkeypatch):
    app = create_app(make_settings(tmp_path), provider=FakeProvider())
    monkeypatch.setattr(main.os, "kill", lambda pid, sig: None)
    app.state.last_activity = -10_000.0
    app.state.in_flight = 1

    async def run():
        watcher = asyncio.create_task(main._idle_watch(app, 0.05))
        await asyncio.sleep(0.1)
        assert not watcher.done()
        app.state.in_flight = 0
        await asyncio.wait_for(watcher, timeout=2)

    asyncio.run(run())


def test_health_reports_the_idle_timer(tmp_path):
    app = create_app(make_settings(tmp_path, idle_shutdown_minutes=30), provider=FakeProvider())
    body = TestClient(app).get("/api/health").json()
    assert body["idle_shutdown"]["after_minutes"] == 30
    assert 0 < body["idle_shutdown"]["remaining_seconds"] <= 1800


def test_disabled_by_default(tmp_path):
    app = create_app(make_settings(tmp_path), provider=FakeProvider())
    assert app.state.settings.idle_shutdown_minutes == 0
    with TestClient(app) as client:  # runs the lifespan; nothing is scheduled
        assert client.get("/api/health").status_code == 200
