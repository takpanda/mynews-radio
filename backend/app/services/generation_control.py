"""Atomic per-owner quota and idempotency control for manual generation."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.connection import get_db_connection

JST = ZoneInfo("Asia/Tokyo")
DAILY_LIMIT = 10
ACTIVE_LIMIT = 1
IDEMPOTENCY_RETENTION = timedelta(hours=24)


class GenerationControlError(Exception):
    def __init__(self, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


@dataclass(frozen=True)
class JobClaim:
    job_id: int
    episode_id: int | None
    duplicate: bool = False


def input_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _jst_day_bounds(now: datetime) -> tuple[str, str]:
    local = now.astimezone(JST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_text(start), _utc_text(start + timedelta(days=1))


def _seconds_until_jst_midnight(now: datetime) -> int:
    local = now.astimezone(JST)
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((tomorrow - local).total_seconds()))


def claim_job(owner_user_id: int, operation: str, idempotency_key: str, payload: object) -> JobClaim:
    """Claim a job and enforce both limits in one SQLite write transaction."""
    if not idempotency_key or len(idempotency_key) > 255:
        raise GenerationControlError(400, "Idempotency-Key is required and must be at most 255 characters")
    digest = input_hash(payload)
    now = datetime.now(timezone.utc)
    retention_cutoff = _utc_text(now - IDEMPOTENCY_RETENTION)
    day_start, day_end = _jst_day_bounds(now)

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM generation_jobs WHERE claimed_at < ?", (retention_cutoff,))
        existing = conn.execute(
            "SELECT id, episode_id, input_hash FROM generation_jobs "
            "WHERE owner_user_id = ? AND operation = ? AND idempotency_key = ?",
            (owner_user_id, operation, idempotency_key),
        ).fetchone()
        if existing:
            if existing["input_hash"] != digest:
                raise GenerationControlError(409, "Idempotency-Key was already used with different input")
            return JobClaim(existing["id"], existing["episode_id"], duplicate=True)

        active = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs WHERE owner_user_id = ? AND status = 'active'",
            (owner_user_id,),
        ).fetchone()["count"]
        if active >= ACTIVE_LIMIT:
            raise GenerationControlError(429, "Another generation is already running", 60)

        daily = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs "
            "WHERE owner_user_id = ? AND claimed_at >= ? AND claimed_at < ?",
            (owner_user_id, day_start, day_end),
        ).fetchone()["count"]
        if daily >= DAILY_LIMIT:
            raise GenerationControlError(429, "Daily generation limit exceeded", _seconds_until_jst_midnight(now))

        cursor = conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash) "
            "VALUES (?, ?, ?, ?)",
            (owner_user_id, operation, idempotency_key, digest),
        )
        return JobClaim(cursor.lastrowid, None)


def bind_episode(job_id: int, episode_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET episode_id = ? WHERE id = ?", (episode_id, job_id))


def finish_job(job_id: int, success: bool) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE generation_jobs SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
            ("completed" if success else "failed", job_id),
        )
