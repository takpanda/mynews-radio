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


def test_api_key_alone_cannot_change_owner_state(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "shared-key")
    from app.config import get_settings
    get_settings.cache_clear()
    client.headers.update({"Authorization": "Bearer shared-key"})

    before = client.get("/settings", headers={"Authorization": "Bearer shared-key"})
    generate = client.post("/generate", json={"date": "2099-01-01"}, headers={"Authorization": "Bearer shared-key"})

    assert before.status_code == 401
    assert generate.status_code == 401
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
            "SELECT operation, owner_user_id, result, episode_id FROM audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["operation"] == "generate"
    assert row["owner_user_id"] is not None
    assert row["result"] == "started"
    assert row["episode_id"] == generated.json()["episode_id"]
