"""生成監査ログの受入条件テスト。"""

import asyncio
import hashlib
import os
import sqlite3
import pytest
import subprocess
import sys
from pathlib import Path
from app.audit import cleanup_audit_logs, hash_input
from app.db.connection import get_db_connection


def test_synthesis_terminal_sse_finishes_job_before_client_disconnect(monkeypatch):
    """complete を受信したクライアントの即時切断でもジョブを残さない。"""
    from fastapi.responses import StreamingResponse
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService
    from app.services.generation_control import claim_job

    episode_id = EpisodeService().create_episode("2099-06-01", status="generating")
    claim = claim_job(1, "synthesize", "disconnect-after-complete", {"episode_id": episode_id})

    def completed_stream(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")
        yield b"event: complete\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_stream_synthesize", completed_stream)
    response = StreamingResponse(
        generate_api._stream_synthesize_with_audit(
            episode_id, generate_api.SynthesizeRequest(), 1, claim.job_id,
        ),
        media_type="text/event-stream",
    )
    complete_sent = asyncio.Event()

    async def receive():
        if not getattr(receive, "requested", False):
            receive.requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await complete_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            complete_sent.set()
            # Give the disconnect listener precedence over the next iteration.
            await asyncio.sleep(0)

    asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send))

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT status, finished_at FROM generation_jobs WHERE id = ?", (claim.job_id,)
        ).fetchone()
    assert row["status"] == "completed"
    assert row["finished_at"] is not None


def test_synthesis_finish_job_failure_is_logged_and_leaves_job_observable(monkeypatch, caplog):
    """SQLite更新失敗はプロセス終了と区別できるエラーログを残す。"""
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService
    from app.services.generation_control import claim_job

    episode_id = EpisodeService().create_episode("2099-06-02", status="generating")
    claim = claim_job(1, "synthesize", "finish-job-locked", {"episode_id": episode_id})

    def completed_stream(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")
        yield b"event: complete\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_stream_synthesize", completed_stream)
    monkeypatch.setattr(
        generate_api, "finish_job",
        lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        list(generate_api._stream_synthesize_with_audit(
            episode_id, generate_api.SynthesizeRequest(), 1, claim.job_id,
        ))

    assert "failed to finish synthesis job" in caplog.text
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT status FROM generation_jobs WHERE id = ?", (claim.job_id,)
        ).fetchone()["status"] == "active"


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
                                                 "tts_engine": None, "url": None, "style": "solo",
                                                 "mc_gender": "male", "settings_snapshot": None})
    assert started["started_at"]
    assert rejected["accepted"] == 0
    assert rejected["rejection_reason"] == "idempotency_key_input_mismatch"
    assert key not in str(dict(started))


def test_audit_endpoint_requires_admin_session(client):
    client.cookies.clear()
    response = client.get("/admin/audit-logs", headers={"Authorization": "Bearer test-admin-key"})
    assert response.status_code == 401


def test_audit_endpoint_does_not_expose_raw_request_secrets(client):
    key = "audit-api-secret-key"
    source_url = "https://example.com/private-article"
    session_token = next(
        cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"
    )
    response = client.post(
        "/generate",
        json={"date": "2099-06-01", "url": source_url},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200

    audit_response = client.get("/admin/audit-logs")
    assert audit_response.status_code == 200
    body = audit_response.text
    assert key not in body
    assert source_url not in body
    assert session_token not in body


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


def test_legacy_migration_preserves_existing_extended_audit_columns():
    from app.db.migration import migrate_audit_logs
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL, "
        "owner_user_id INTEGER, actor_user_id INTEGER, generation_job_id INTEGER, "
        "idempotency_key_hash TEXT, input_hash TEXT, executed_at TEXT NOT NULL, "
        "result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure')), accepted INTEGER, "
        "rejection_reason TEXT, started_at TEXT, ended_at TEXT, episode_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO audit_logs(operation, owner_user_id, actor_user_id, generation_job_id, "
        "idempotency_key_hash, input_hash, executed_at, result, accepted, rejection_reason, "
        "started_at, ended_at, episode_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("generate", 1, 2, 3, "key-hash", "input-hash", "2026-01-01T00:00:00+00:00",
         "failure", 1, "none", "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00", 9),
    )
    assert migrate_audit_logs(conn) is True
    row = conn.execute(
        "SELECT actor_user_id, generation_job_id, idempotency_key_hash, input_hash, "
        "accepted, rejection_reason, started_at, ended_at, episode_id FROM audit_logs"
    ).fetchone()
    assert dict(row) == {
        "actor_user_id": 2,
        "generation_job_id": 3,
        "idempotency_key_hash": "key-hash",
        "input_hash": "input-hash",
        "accepted": 1,
        "rejection_reason": "none",
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": "2026-01-01T00:01:00+00:00",
        "episode_id": 9,
    }
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


def test_episode_creation_failure_closes_started_audit(monkeypatch):
    from app.services import generation_control

    monkeypatch.setattr(generation_control, "_insert_episode", lambda *args: (_ for _ in ()).throw(RuntimeError("insert failed")))
    try:
        generation_control.claim_job(
            1, "generate", "episode-create-failure", {"date": "2099-06-06"},
            episode_date="2099-06-06",
        )
    except RuntimeError:
        pass
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT result FROM audit_logs WHERE generation_job_id = "
            "(SELECT id FROM generation_jobs WHERE idempotency_key = 'episode-create-failure') ORDER BY id"
        ).fetchall()
        assert [row["result"] for row in rows] == ["started", "failure"]


def test_run_daily_invokes_retention_cleanup(monkeypatch):
    from app.batch import run_daily

    monkeypatch.setattr(run_daily, "setup_daily_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {"audit_deleted_count": 1})
    monkeypatch.setattr(run_daily.EpisodeService, "create_radio_episode", lambda *args, **kwargs: (1, 0))
    monkeypatch.setattr(run_daily, "run_radio_pipeline", lambda *args, **kwargs: run_daily.PipelineResult.NO_CONTENT)
    monkeypatch.setattr(run_daily, "_write_manifest", lambda *args, **kwargs: None)
    called = []
    original = run_daily.cleanup_episodes
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: (called.append(True) or original()))
    run_daily.main()
    assert called == [True]


def test_old_audit_schema_app_startup_migrates_before_actor_index(tmp_path):
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL, "
        "owner_user_id INTEGER, executed_at TEXT NOT NULL, "
        "result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure')), episode_id INTEGER)"
    )
    conn.commit()
    conn.close()
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    env["EPISODES_DIR"] = str(tmp_path / "episodes")
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_file) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_logs)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(audit_logs)")}
    assert "actor_user_id" in columns
    assert "idx_audit_logs_actor" in indexes


def test_active_and_daily_quota_rejections_are_audited(client):
    from app.services.generation_control import claim_job, finish_job

    active = claim_job(1, "generate", "quota-active-holder", {"date": "2099-06-10"})
    response = client.post(
        "/generate",
        json={"date": "2099-06-11"},
        headers={"Idempotency-Key": "quota-active-rejected"},
    )
    assert response.status_code == 429
    finish_job(active.job_id, False)

    # active holder itself counts toward the daily quota.
    for index in range(9):
        claim = claim_job(1, "generate", f"quota-daily-{index}", {"index": index})
        finish_job(claim.job_id, True)
    response = client.post(
        "/generate",
        json={"date": "2099-06-12"},
        headers={"Idempotency-Key": "quota-daily-rejected"},
    )
    assert response.status_code == 429

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT idempotency_key_hash, accepted, rejection_reason FROM audit_logs "
            "WHERE result = 'rejected' AND idempotency_key_hash IN (?, ?) ORDER BY id",
            (
                hashlib.sha256(b"quota-active-rejected").hexdigest(),
                hashlib.sha256(b"quota-daily-rejected").hexdigest(),
            ),
        ).fetchall()
    assert [(row["accepted"], row["rejection_reason"]) for row in rows] == [
        (0, "active_limit"),
        (0, "daily_limit"),
    ]


def test_synthesis_claim_audit_failure_rolls_back_job_and_start_audit(client, monkeypatch):
    from app.services import generation_control
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-06-13", status="generating")
    monkeypatch.setattr(
        generation_control,
        "insert_audit_log",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
    )
    with pytest.raises(OSError):
        generation_control.claim_job(
            1,
            "synthesize",
            "synthesis-atomic-failure",
            {"episode_id": episode_id, "body": {"tts_engine": "voicevox"}},
            episode_id=episode_id,
        )
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM generation_jobs WHERE idempotency_key = 'synthesis-atomic-failure'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE operation = 'synthesize'"
        ).fetchone()[0] == 0
