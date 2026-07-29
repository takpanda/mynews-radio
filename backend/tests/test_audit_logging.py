"""生成監査ログの受入条件テスト。"""

import hashlib
import pytest
from app.audit import cleanup_audit_logs, hash_input
from app.db.connection import get_db_connection


def test_generation_audit_contains_hashes_and_rejection_reason(client):
    key = "audit-key-1"
    response = client.post(
        "/generate",
        json={"date": "2099-06-01"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200

    changed = client.post(
        "/generate",
        json={"date": "2099-06-02"},
        headers={"Idempotency-Key": key},
    )
    assert changed.status_code == 409

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id"
        ).fetchall()
    started = next(row for row in rows if row["result"] == "started")
    rejected = next(row for row in rows if row["result"] == "rejected")
    assert started["episode_id"] == response.json()["episode_id"]
    assert started["actor_user_id"] is not None
    assert started["idempotency_key_hash"] == hashlib.sha256(key.encode()).hexdigest()
    assert started["input_hash"] == hash_input({"date": "2099-06-01", "max_articles": None,
                                                 "duration_minutes": None, "news_source": "hatena_bookmark",
                                                 "tts_engine": "aivispeech", "url": None, "style": "solo",
                                                 "mc_gender": "male", "settings_snapshot": None})
    assert started["started_at"]
    assert rejected["accepted"] == 0
    assert rejected["rejection_reason"] == "idempotency_key_input_mismatch"
    assert key not in str(dict(started))


def test_audit_endpoint_requires_admin_session(client):
    client.cookies.clear()
    response = client.get("/admin/audit-logs", headers={"Authorization": "Bearer test-admin-key"})
    assert response.status_code == 401


def test_audit_retention_deletes_only_logs_older_than_90_days(client):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs(operation, owner_user_id, actor_user_id, executed_at, result, accepted) "
            "VALUES ('retention', 1, 1, datetime('now', '-91 days'), 'failure', 1)"
        )
        conn.execute(
            "INSERT INTO audit_logs(operation, owner_user_id, actor_user_id, executed_at, result, accepted) "
            "VALUES ('retention', 1, 1, datetime('now', '-1 days'), 'failure', 1)"
        )
    assert cleanup_audit_logs() == 1
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE operation = 'retention'"
        ).fetchone()[0] == 1


def test_audit_write_failure_does_not_start_generation(client, monkeypatch):
    from app.services import generation_control

    def fail_audit(*args, **kwargs):
        raise OSError("audit unavailable")

    monkeypatch.setattr(generation_control, "insert_audit_log", fail_audit)
    with pytest.raises(OSError):
        client.post(
            "/generate",
            json={"date": "2099-06-03"},
            headers={"Idempotency-Key": "audit-failure"},
        )
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE episode_date = '2099-06-03'"
        ).fetchone()[0] == 0
