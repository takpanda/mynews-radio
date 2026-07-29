from datetime import datetime, timedelta, timezone

from app.audit import cleanup_audit_logs, hash_value, insert_audit_log
from app.db.connection import get_db_connection


def test_audit_log_hashes_identifiers_and_records_rejection(client):
    with get_db_connection() as conn:
        insert_audit_log(
            conn, operation="generate", actor_user_id=1, result="rejected",
            idempotency_key_hash=hash_value("secret-key"), input_hash="input-digest",
            rejection_reason="quota exceeded", accepted=False,
        )
        row = conn.execute(
            "SELECT accepted, rejection_reason, idempotency_key_hash, input_hash, "
            "actor_user_id, started_at, ended_at FROM audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["accepted"] == 0
    assert row["rejection_reason"] == "quota exceeded"
    assert row["idempotency_key_hash"] != "secret-key"
    assert len(row["idempotency_key_hash"]) == 64
    assert row["input_hash"] == "input-digest"
    assert row["actor_user_id"] == 1
    assert row["started_at"] is None
    assert row["ended_at"] is not None


def test_audit_retention_deletes_only_logs_older_than_90_days():
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=89)).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs(operation, owner_user_id, executed_at, result, started_at) "
            "VALUES (?, ?, ?, ?, ?)", ("old", 1, old, "failure", old)
        )
        conn.execute(
            "INSERT INTO audit_logs(operation, owner_user_id, executed_at, result, started_at) "
            "VALUES (?, ?, ?, ?, ?)", ("recent", 1, recent, "failure", recent)
        )
    deleted = cleanup_audit_logs()
    assert deleted == 1
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE operation = 'old'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE operation = 'recent'").fetchone()[0] == 1


def test_audit_endpoint_requires_admin_session(client):
    client.cookies.clear()
    assert client.get("/admin/audit-logs").status_code == 401
