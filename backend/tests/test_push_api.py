import base64
import sqlite3


ENDPOINT = "https://push.example.test/send/opaque-token"
KEYS = {
    "p256dh": base64.urlsafe_b64encode(b"p256dh-key-material").decode().rstrip("="),
    "auth": base64.urlsafe_b64encode(b"auth-key").decode().rstrip("="),
}


def test_vapid_public_key_returns_only_public_key(client, monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPublicKey")
    from app.config import get_settings
    get_settings.cache_clear()

    response = client.get("/push/vapid-public-key")

    assert response.status_code == 200
    assert response.json() == {"public_key": "BPublicKey"}


def test_register_is_idempotent_and_does_not_expose_subscription(client):
    response = client.post("/push/subscriptions", json={"endpoint": ENDPOINT, "keys": KEYS})
    assert response.status_code == 200
    subscription_id = response.json()["subscription_id"]
    assert ENDPOINT not in response.text
    assert KEYS["p256dh"] not in response.text

    response2 = client.post("/push/subscriptions", json={"endpoint": ENDPOINT, "keys": KEYS})
    assert response2.status_code == 200
    assert response2.json()["subscription_id"] != subscription_id

    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 1
        assert conn.execute("SELECT is_active FROM push_subscriptions").fetchone()[0] == 1


def test_unregister_is_idempotent_and_uses_opaque_identifier(client):
    response = client.post("/push/subscriptions", json={"endpoint": ENDPOINT, "keys": KEYS})
    subscription_id = response.json()["subscription_id"]

    assert client.delete(f"/push/subscriptions/{subscription_id}").status_code == 204
    assert client.delete(f"/push/subscriptions/{subscription_id}").status_code == 204

    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        assert conn.execute("SELECT is_active FROM push_subscriptions").fetchone()[0] == 0


def test_invalid_subscription_is_rejected_without_echoing_endpoint(client):
    response = client.post(
        "/push/subscriptions",
        json={"endpoint": "http://", "keys": KEYS},
    )
    assert response.status_code == 422
    assert ENDPOINT not in response.text


def test_push_rate_limit_returns_existing_error_shape(client, monkeypatch):
    monkeypatch.setenv("PUSH_RATE_LIMIT", "0/minute")
    from app.config import get_settings
    get_settings.cache_clear()

    response = client.post("/push/subscriptions", json={"endpoint": ENDPOINT, "keys": KEYS})

    assert response.status_code == 429
    assert response.json() == {"detail": "Rate limit exceeded. Try again later."}
