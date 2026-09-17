"""BEE-958 永続FIFOキューの受入テスト。"""

import sqlite3

import pytest

from app.db.connection import get_db_connection
from app.services.generation_control import (
    GenerationControlError,
    SYSTEM_OWNER_USERNAME,
    enqueue_job,
    promote_next_job,
)


def test_enqueue_persists_payload_and_fifo_promotion(client):
    active = enqueue_job(1, "generate", "fifo-1", {"date": "2099-01-01"}, episode_date="2099-01-01")
    waiting = enqueue_job(1, "commentary", "fifo-2", {"date": "2099-01-02"}, episode_date="2099-01-02", episode_type="commentary", source_url="https://example.com/a")

    assert active.status == "active"
    assert waiting.status == "waiting"
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, payload FROM generation_jobs WHERE id = ?", (waiting.job_id,)).fetchone()
        episode = conn.execute("SELECT status FROM episodes WHERE id = ?", (waiting.episode_id,)).fetchone()
        audit = conn.execute(
            "SELECT started_at FROM audit_logs WHERE generation_job_id = ? AND result = 'started'",
            (waiting.job_id,),
        ).fetchone()
    assert row["status"] == "waiting"
    assert row["payload"] == '{"date":"2099-01-02"}'
    assert episode["status"] == "waiting"
    assert audit["started_at"] is None

    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))
    promoted = promote_next_job()
    assert promoted is not None
    with get_db_connection() as conn:
        row = conn.execute("SELECT status FROM generation_jobs WHERE id = ?", (waiting.job_id,)).fetchone()
        audit = conn.execute(
            "SELECT started_at FROM audit_logs WHERE generation_job_id = ? AND result = 'started'",
            (waiting.job_id,),
        ).fetchone()
    assert row["status"] == "active"
    assert audit["started_at"] is not None


def test_waiting_limit_is_for_api_only_and_cron_is_exempt(client, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_JOBS", "1")
    from app.config import get_settings
    get_settings.cache_clear()

    active = enqueue_job(1, "generate", "limit-active", {"n": 1}, episode_date="2099-02-01")
    enqueue_job(1, "generate", "limit-waiting", {"n": 2}, episode_date="2099-02-02")
    with pytest.raises(GenerationControlError) as exc_info:
        enqueue_job(1, "generate", "limit-rejected", {"n": 3}, episode_date="2099-02-03")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 60

    with get_db_connection() as conn:
        conn.execute("INSERT INTO admin_users(username, password_hash) VALUES (?, ?)", (SYSTEM_OWNER_USERNAME, "disabled$generation_queue"))
        owner_id = conn.execute("SELECT id FROM admin_users WHERE username = ?", (SYSTEM_OWNER_USERNAME,)).fetchone()[0]
    cron = enqueue_job(owner_id, "daily", "limit-cron", {"date": "2099-02-04"}, episode_date="2099-02-04")
    assert cron.status == "waiting"
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))


def test_generate_api_returns_waiting_when_another_job_is_active(client, monkeypatch):
    from app.api import generate as generate_api

    active = enqueue_job(1, "generate", "api-active", {"date": "2099-02-10"}, episode_date="2099-02-10")
    monkeypatch.setattr(generate_api, "dispatch_job", lambda _job_id: None)
    response = client.post(
        "/generate",
        json={"date": "2099-02-11"},
        headers={"Idempotency-Key": "api-waiting"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "waiting"
    with get_db_connection() as conn:
        episode = conn.execute("SELECT status FROM episodes WHERE id = ?", (response.json()["episode_id"],)).fetchone()
    assert episode["status"] == "waiting"
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))


def test_promotion_is_conditional_and_keeps_old_rows(client):
    active = enqueue_job(1, "generate", "conditional-active", {"n": 1}, episode_date="2099-03-01")
    waiting = enqueue_job(1, "generate", "conditional-waiting", {"n": 2}, episode_date="2099-03-02")
    assert promote_next_job() is None
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))
    assert promote_next_job() is not None
    with get_db_connection() as conn:
        row = conn.execute("SELECT status FROM generation_jobs WHERE id = ?", (waiting.job_id,)).fetchone()
    assert row["status"] == "active"


def test_legacy_generation_jobs_migration_preserves_rows(tmp_path):
    from app.db.migration import migrate_generation_jobs

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE admin_users(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);"
        "CREATE TABLE episodes(id INTEGER PRIMARY KEY, episode_date TEXT);"
        "CREATE TABLE generation_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id INTEGER NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, input_hash TEXT NOT NULL, episode_id INTEGER, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','failed')), claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);"
    )
    conn.execute("INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash) VALUES (1, 'generate', 'legacy', 'hash')")
    conn.commit()
    assert migrate_generation_jobs(conn) is True
    row = conn.execute("SELECT id, status, payload FROM generation_jobs").fetchone()
    assert (row["id"], row["status"], row["payload"]) == (1, "active", "{}")
    conn.close()


def test_generation_jobs_migration_recovers_orphaned_rebuild_table(tmp_path):
    from app.db.migration import migrate_generation_jobs

    db = tmp_path / "interrupted-migration.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE admin_users(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);"
        "CREATE TABLE episodes(id INTEGER PRIMARY KEY, episode_date TEXT);"
        "CREATE TABLE generation_jobs_new("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id INTEGER NOT NULL, operation TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL, input_hash TEXT NOT NULL, client_ip_hash TEXT NOT NULL DEFAULT '', "
        "payload TEXT NOT NULL DEFAULT '{}', episode_id INTEGER, status TEXT NOT NULL DEFAULT 'active' "
        "CHECK(status IN ('waiting','active','completed','failed')), claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "finished_at TEXT);"
    )
    conn.execute(
        "INSERT INTO generation_jobs_new(owner_user_id, operation, idempotency_key, input_hash, status) "
        "VALUES (1, 'generate', 'recovered', 'hash', 'waiting')"
    )
    conn.commit()

    assert migrate_generation_jobs(conn) is False
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'generation_jobs_new'"
    ).fetchone() is None
    row = conn.execute("SELECT id, status, payload FROM generation_jobs").fetchone()
    assert (row["id"], row["status"], row["payload"]) == (1, "waiting", "{}")
    conn.close()


def test_startup_recovery_fails_active_and_promotes_waiting(client, monkeypatch):
    import app.services.generation_control as control

    active = enqueue_job(1, "generate", "recovery-active", {"n": 1}, episode_date="2099-05-01")
    waiting = enqueue_job(1, "generate", "recovery-waiting", {"n": 2}, episode_date="2099-05-02")
    monkeypatch.setattr(control._dispatcher, "notify", lambda _job_id=None: None)

    control.recover_generation_queue()

    with get_db_connection() as conn:
        jobs = conn.execute(
            "SELECT id, status FROM generation_jobs WHERE id IN (?, ?) ORDER BY id",
            (active.job_id, waiting.job_id),
        ).fetchall()
        episode = conn.execute("SELECT status FROM episodes WHERE id = ?", (waiting.episode_id,)).fetchone()
    assert [(row["id"], row["status"]) for row in jobs] == [
        (active.job_id, "failed"), (waiting.job_id, "active")
    ]
    assert episode["status"] == "generating"


def test_synthesize_api_returns_waiting_when_another_job_is_active(client, monkeypatch):
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    active = enqueue_job(1, "generate", "synth-active", {"n": 1}, episode_date="2099-06-01")
    episode_id = EpisodeService().create_episode("2099-06-02", status="pending")
    monkeypatch.setattr(generate_api, "dispatch_job", lambda _job_id: None)

    response = client.post(
        f"/episodes/{episode_id}/synthesize",
        json={"tts_engine": "voicevox"},
        headers={"Idempotency-Key": "synth-waiting"},
    )

    assert response.status_code == 200
    assert '"status": "waiting"' in response.text
    with get_db_connection() as conn:
        job = conn.execute(
            "SELECT status FROM generation_jobs WHERE operation = 'synthesize' AND episode_id = ?",
            (episode_id,),
        ).fetchone()
        episode = conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))
    assert job["status"] == "waiting"
    assert episode["status"] == "waiting"


@pytest.mark.parametrize("result", [True, False])
def test_daily_queued_job_finalizes_audit_before_finish(client, monkeypatch, result):
    from app.api import generate as generate_api
    from app.batch import run_daily

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO admin_users(username, password_hash) VALUES (?, ?)",
            (SYSTEM_OWNER_USERNAME, "disabled$generation_queue"),
        )
        owner_id = conn.execute(
            "SELECT id FROM admin_users WHERE username = ?", (SYSTEM_OWNER_USERNAME,)
        ).fetchone()[0]
    claim = enqueue_job(
        owner_id, "daily", f"daily-audit-{result}", {"date": "2099-07-01"},
        episode_date="2099-07-01", dispatch=False,
    )
    with get_db_connection() as conn:
        job = conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (claim.job_id,)).fetchone()
    monkeypatch.setattr(run_daily, "run_daily_job", lambda _job: result)
    finished = []
    monkeypatch.setattr(generate_api, "finish_job", lambda job_id, success: finished.append((job_id, success)))

    generate_api.execute_queued_job(job)

    with get_db_connection() as conn:
        audit = conn.execute(
            "SELECT result, started_at, ended_at FROM audit_logs "
            "WHERE generation_job_id = ? ORDER BY id DESC LIMIT 1",
            (claim.job_id,),
        ).fetchone()
    assert audit["result"] == ("success" if result else "failure")
    assert audit["started_at"] is None
    assert audit["ended_at"] is not None
    assert finished == [(claim.job_id, result)]
