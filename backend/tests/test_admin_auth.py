import sqlite3

from app.auth import hash_password


def _create_admin(monkeypatch, username="admin", password="password"):
    from app import config as cfg_mod
    from app.db.connection import get_db_connection

    monkeypatch.setenv("API_KEY", "")
    cfg_mod.get_settings.cache_clear()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        return cursor.lastrowid


def test_login_sets_secure_http_only_cookie(client, monkeypatch):
    user_id = _create_admin(monkeypatch)
    client.headers.pop("Authorization", None)
    response = client.post(
        "/admin/login", json={"username": "admin", "password": "password"}
    )
    assert response.status_code == 200
    assert response.json()["admin_user_id"] == user_id
    cookie = response.headers["set-cookie"]
    assert "admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie


def test_invalid_credentials_are_rejected(client, monkeypatch):
    _create_admin(monkeypatch)
    client.headers.pop("Authorization", None)
    response = client.post(
        "/admin/login", json={"username": "admin", "password": "wrong"}
    )
    assert response.status_code == 401


def test_session_auth_and_logout_invalidate_cookie(client, monkeypatch):
    _create_admin(monkeypatch)
    client.headers.pop("Authorization", None)
    login = client.post(
        "/admin/login", json={"username": "admin", "password": "password"}
    )
    assert login.status_code == 200
    client.cookies.set("admin_session", login.cookies["admin_session"])
    assert client.get("/admin/me").status_code == 200

    logout = client.post("/admin/logout")
    assert logout.status_code == 200
    assert 'admin_session=""' in logout.headers["set-cookie"]
    assert client.get("/admin/me").status_code == 401


def test_admin_dictionary_requires_session_when_api_key_unset(client, monkeypatch):
    _create_admin(monkeypatch)
    client.headers.pop("Authorization", None)
    assert client.get("/admin/dictionary").status_code == 401
    assert client.post("/admin/dictionary", json={}).status_code == 401
    assert client.put("/admin/dictionary/1", json={}).status_code == 401
    assert client.patch("/admin/dictionary/1/status", json={}).status_code == 401


def test_bearer_api_key_remains_compatible_without_admin_account(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "service-key")
    from app import config as cfg_mod
    cfg_mod.get_settings.cache_clear()
    client.headers.update({"Authorization": "Bearer service-key"})
    assert client.get("/admin/dictionary").status_code == 200
