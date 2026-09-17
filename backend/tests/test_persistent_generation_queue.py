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
    assert row["status"] == "waiting"
    assert row["payload"] == '{"date":"2099-01-02"}'
    assert episode["status"] == "waiting"

    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = ?", (active.job_id,))
    promoted = promote_next_job()
    assert promoted is not None
    with get_db_connection() as conn:
        row = conn.execute("SELECT status FROM generation_jobs WHERE id = ?", (waiting.job_id,)).fetchone()
    assert row["status"] == "active"


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
