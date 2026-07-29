"""生成監査ログの受入条件テスト。"""

import hashlib
import sqlite3
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


def test_synthesis_idempotency_rejection_is_audited(client):
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-06-04", status="generating")
    key = "synthesis-audit-key"
    first = client.post(
        f"/episodes/{episode_id}/synthesize", json={"tts_engine": "voicevox"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200
    second = client.post(
        f"/episodes/{episode_id}/synthesize", json={"tts_engine": "aivispeech"},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 409
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT operation, accepted, rejection_reason FROM audit_logs "
            "WHERE operation = 'synthesize' AND result = 'rejected' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["operation"] == "synthesize"
    assert row["accepted"] == 0
    assert row["rejection_reason"] == "idempotency_key_input_mismatch"


def test_legacy_audit_table_migration_allows_rejected_rows():
    from app.db.migration import migrate_audit_logs
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL, "
        "owner_user_id INTEGER, executed_at TEXT NOT NULL, "
        "result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure')), episode_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO audit_logs(operation, executed_at, result) VALUES ('generate', '2020-01-01', 'failure')"
    )
    assert migrate_audit_logs(conn) is True
    conn.execute(
        "INSERT INTO audit_logs(operation, executed_at, result, accepted) "
        "VALUES ('generate', '2020-01-02', 'rejected', 0)"
    )
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2
    conn.close()


def test_finalize_audit_failure_marks_job_failed(monkeypatch):
    from app.api import generate as generate_api
    from app.services.generation_control import claim_job

    claim = claim_job(1, "generate", "finalize-failure", {"date": "2099-06-05"})
    monkeypatch.setattr(generate_api, "finalize_audit_log", lambda *args: (_ for _ in ()).throw(OSError("audit unavailable")))
    generate_api._run_pipeline_with_audit(
        999999, generate_api.GenerateRequest(date="2099-06-05"),
        lambda *_args: None, 1, "generate", claim.job_id,
    )
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT status FROM generation_jobs WHERE id = ?", (claim.job_id,)
        ).fetchone()[0] == "failed"
