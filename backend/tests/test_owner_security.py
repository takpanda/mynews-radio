import time

from app.auth import hash_password
from app.db.connection import get_db_connection


def _login(client):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            ("owner", hash_password("password")),
        )
    response = client.post("/admin/login", json={"username": "owner", "password": "password"})
    assert response.status_code == 200
    client.headers.pop("Authorization", None)
    client.cookies.set("admin_session", response.cookies["admin_session"])
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT id FROM admin_users WHERE username = ?", ("owner",)
        ).fetchone()[0]


def test_api_key_alone_cannot_change_owner_state(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "shared-key")
    from app.config import get_settings
    get_settings.cache_clear()
    client.headers.update({"Authorization": "Bearer shared-key"})
    client.cookies.clear()

    before = client.get("/settings", headers={"Authorization": "Bearer shared-key"})
    update = client.put(
        "/settings",
        json={"priority_themes": [], "excluded_themes": [], "duration_preset": "short"},
        headers={"Authorization": "Bearer shared-key"},
    )
    reset = client.delete("/settings", headers={"Authorization": "Bearer shared-key"})
    generate = client.post("/generate", json={"date": "2099-01-01"}, headers={"Authorization": "Bearer shared-key"})
    commentary = client.post(
        "/generate",
        json={"date": "2099-01-02", "url": "https://example.com/article"},
        headers={"Authorization": "Bearer shared-key"},
    )
    synthesize = client.post(
        "/episodes/999/synthesize",
        json={"tts_engine": "voicevox"},
        headers={"Authorization": "Bearer shared-key"},
    )

    assert before.status_code == 401
    assert update.status_code == 401
    assert reset.status_code == 401
    assert generate.status_code == 401
    assert commentary.status_code == 401
    assert synthesize.status_code == 401
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0


def test_authenticated_owner_can_read_settings_and_audit_generation(client):
    _login(client)
    response = client.get("/settings")
    assert response.status_code == 200

    generated = client.post("/generate", json={"date": "2099-01-02"})
    assert generated.status_code == 200
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT operation, owner_user_id, result, episode_id
            FROM audit_logs
            WHERE operation = 'generate' AND result = 'started'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    assert row["operation"] == "generate"
    assert row["owner_user_id"] is not None
    assert row["result"] == "started"
    assert row["episode_id"] == generated.json()["episode_id"]


def test_authenticated_owner_can_update_and_reset_settings(client):
    _login(client)
    updated = client.put(
        "/settings",
        json={"priority_themes": ["technology"], "excluded_themes": [], "duration_preset": "short"},
    )
    reset = client.delete("/settings")
    assert updated.status_code == 200
    assert updated.json()["duration_preset"] == "short"
    assert reset.status_code == 200
    assert reset.json()["duration_preset"] == "normal"


def _audit_rows(operation):
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT owner_user_id, executed_at, result, episode_id FROM audit_logs WHERE operation = ? ORDER BY id",
            (operation,),
        ).fetchall()


def _wait_for_audit_count(operation, count):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = _audit_rows(operation)
        if len(rows) >= count:
            return rows
        time.sleep(0.01)
    return _audit_rows(operation)


def test_radio_generation_records_success_and_failure_audit(client, monkeypatch):
    owner_id = _login(client)
    from app.services.episode_service import EpisodeService
    from app.api import generate as generate_api

    def fake_success(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")

    monkeypatch.setattr(generate_api, "_run_generation", fake_success)
    success = client.post("/generate", json={"date": "2099-01-03"})
    assert success.status_code == 200
    _wait_for_audit_count("generate", 2)

    def fake_failure(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "failed")

    monkeypatch.setattr(generate_api, "_run_generation", fake_failure)
    failure = client.post("/generate", json={"date": "2099-01-04"})
    assert failure.status_code == 200
    _wait_for_audit_count("generate", 4)

    rows = _wait_for_audit_count("generate", 4)
    assert [row["result"] for row in rows[-4:]] == ["started", "success", "started", "failure"]
    assert all(row["owner_user_id"] == owner_id and row["executed_at"] for row in rows[-4:])


def test_commentary_generation_records_success_and_failure_audit(client, monkeypatch):
    owner_id = _login(client)
    from app.services.episode_service import EpisodeService
    from app.api import generate as generate_api

    def fake_success(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")

    monkeypatch.setattr(generate_api, "_run_commentary_generation", fake_success)
    success = client.post("/generate", json={"date": "2099-01-05", "url": "https://example.com/success"})
    assert success.status_code == 200

    def fake_failure(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "failed")

    monkeypatch.setattr(generate_api, "_run_commentary_generation", fake_failure)
    failure = client.post("/generate", json={"date": "2099-01-06", "url": "https://example.com/failure"})
    assert failure.status_code == 200

    rows = _wait_for_audit_count("commentary", 4)
    assert [row["result"] for row in rows[-4:]] == ["started", "success", "started", "failure"]
    assert all(row["owner_user_id"] == owner_id and row["executed_at"] for row in rows[-4:])


def test_synthesis_records_success_and_failure_audit(client, monkeypatch):
    owner_id = _login(client)
    from app.services.episode_service import EpisodeService
    from app.api import generate as generate_api

    def fake_success(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")
        yield b"event: complete\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_stream_synthesize", fake_success)
    success_id = EpisodeService().create_episode("2099-01-07", status="generating")
    success = client.post(f"/episodes/{success_id}/synthesize", json={"tts_engine": "voicevox"})
    assert success.status_code == 200

    def fake_failure(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "failed")
        yield b"event: error\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_stream_synthesize", fake_failure)
    failure_id = EpisodeService().create_episode("2099-01-08", status="generating")
    failure = client.post(f"/episodes/{failure_id}/synthesize", json={"tts_engine": "voicevox"})
    assert failure.status_code == 200

    rows = _wait_for_audit_count("synthesize", 4)
    assert [row["result"] for row in rows[-4:]] == ["started", "success", "started", "failure"]
    assert all(row["owner_user_id"] == owner_id and row["executed_at"] for row in rows[-4:])
