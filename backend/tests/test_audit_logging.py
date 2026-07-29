"""生成監査ログの受入条件テスト。"""

import hashlib
import pytest
import sqlite3
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


def test_episode_creation_failure_records_terminal_failure(client, monkeypatch):
    from app.api import generate as generate_api

    monkeypatch.setattr(
        generate_api.EpisodeService,
        "create_radio_episode",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("create failed")),
    )
    with pytest.raises(sqlite3.OperationalError):
        client.post(
            "/generate",
            json={"date": "2099-06-04"},
            headers={"Idempotency-Key": "create-failure"},
        )

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT result FROM audit_logs WHERE idempotency_key_hash = ? ORDER BY id",
            (hashlib.sha256(b"create-failure").hexdigest(),),
        ).fetchall()
        job = conn.execute(
            "SELECT status FROM generation_jobs WHERE idempotency_key = 'create-failure'"
        ).fetchone()
    assert [row["result"] for row in rows] == ["started", "failure"]
    assert job["status"] == "failed"


def test_terminal_audit_failure_still_finishes_job(client, monkeypatch):
    from app.api import generate as generate_api
    from app.services.generation_control import claim_job

    claim = claim_job(1, "generate", "terminal-audit-failure", {"date": "2099-06-05"})
    monkeypatch.setattr(generate_api, "finalize_audit_log", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")))
    generate_api._run_pipeline_with_audit(
        1,
        generate_api.GenerateRequest(date="2099-06-05"),
        lambda *_args: None,
        1,
        "generate",
        claim.job_id,
    )
    with get_db_connection() as conn:
        status = conn.execute(
            "SELECT status FROM generation_jobs WHERE id = ?", (claim.job_id,)
        ).fetchone()["status"]
    assert status == "failed"


def test_daily_batch_executes_audit_retention_cleanup(monkeypatch):
    from app.batch import run_daily

    calls = []
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: calls.append(True) or {"audit_deleted_count": 1})
    monkeypatch.setattr(run_daily, "setup_daily_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_daily.EpisodeService, "create_radio_episode", lambda *args, **kwargs: (1, 0))
    monkeypatch.setattr(run_daily, "run_radio_pipeline", lambda *args, **kwargs: run_daily.PipelineResult.NO_CONTENT)
    monkeypatch.setattr(run_daily, "_write_manifest", lambda *args, **kwargs: None)

    run_daily.main()
    assert calls == [True]


def test_old_audit_schema_migrates_to_allow_rejected_events():
    from app.db.migration import migrate_audit_logs

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE admin_users (id INTEGER PRIMARY KEY);
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            owner_user_id INTEGER,
            executed_at TEXT NOT NULL,
            result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure')),
            episode_id INTEGER
        );
        INSERT INTO audit_logs(operation, owner_user_id, executed_at, result)
        VALUES ('generate', 1, CURRENT_TIMESTAMP, 'started');
        """
    )
    assert migrate_audit_logs(conn) is True
    conn.execute(
        "INSERT INTO audit_logs(operation, actor_user_id, executed_at, result, accepted, rejection_reason) "
        "VALUES ('generate', 1, CURRENT_TIMESTAMP, 'rejected', 0, 'active_limit')"
    )
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2
    conn.close()


def test_synthesis_quota_rejection_is_audited(client):
    from app.services.episode_service import EpisodeService
    from app.services.generation_control import claim_job, finish_job

    episode_id = EpisodeService().create_episode("2099-06-06", status="generating")
    active = claim_job(1, "generate", "active-for-synthesis", {"date": "2099-06-07"})
    response = client.post(
        f"/episodes/{episode_id}/synthesize",
        json={"tts_engine": "voicevox"},
        headers={"Idempotency-Key": "synthesis-rejected"},
    )
    finish_job(active.job_id, False)
    assert response.status_code == 429
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT operation, result, accepted, rejection_reason FROM audit_logs "
            "WHERE idempotency_key_hash = ?",
            (hashlib.sha256(b"synthesis-rejected").hexdigest(),),
        ).fetchone()
    assert dict(row) == {
        "operation": "synthesize",
        "result": "rejected",
        "accepted": 0,
        "rejection_reason": "active_limit",
    }
