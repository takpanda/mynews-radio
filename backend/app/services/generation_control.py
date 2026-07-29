"""Atomic per-owner quota and idempotency control for manual generation."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.connection import get_db_connection
from app.audit import hash_value, insert_audit_log

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
    status: str = "active"
    audit_id: int | None = None


def input_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _jst_day_bounds(now: datetime) -> tuple[str, str]:
    local = now.astimezone(JST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_text(start), _utc_text(start + timedelta(days=1))


def _seconds_until_jst_midnight(now: datetime) -> int:
    local = now.astimezone(JST)
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((tomorrow - local).total_seconds()))


def _insert_episode(conn, episode_date: str, episode_type: str, source_url: str | None) -> int:
    if episode_type == "radio":
        conn.execute(
            "UPDATE episodes SET status = 'failed', updated_at = CURRENT_TIMESTAMP "
            "WHERE episode_date = ? AND type = 'radio' AND status = 'generating'",
            (episode_date,),
        )
        cursor = conn.execute(
            "INSERT INTO episodes (episode_date, seq, status, type) "
            "SELECT ?, COALESCE(MAX(seq), -1) + 1, 'generating', 'radio' "
            "FROM episodes WHERE episode_date = ? AND type = 'radio'",
            (episode_date, episode_date),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO episodes (episode_date, status, type, source_url) VALUES (?, 'generating', ?, ?)",
            (episode_date, episode_type, source_url),
        )
    return int(cursor.lastrowid)


def claim_job(
    owner_user_id: int,
    operation: str,
    idempotency_key: str,
    payload: object,
    *,
    episode_date: str | None = None,
    episode_type: str = "radio",
    source_url: str | None = None,
) -> JobClaim:
    """Claim a job and enforce both limits in one SQLite write transaction."""
    digest = input_hash(payload)
    key_digest = hash_value(idempotency_key) if idempotency_key else None
    if not idempotency_key or len(idempotency_key) > 255:
        with get_db_connection() as conn:
            insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                             idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                             rejection_reason="invalid_idempotency_key")
        raise GenerationControlError(400, "Idempotency-Key is required and must be at most 255 characters")
    now = _utc_now()
    retention_cutoff = _utc_text(now - IDEMPOTENCY_RETENTION)
    day_start, day_end = _jst_day_bounds(now)

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM generation_jobs WHERE claimed_at < ?", (retention_cutoff,))
        existing = conn.execute(
            "SELECT id, episode_id, input_hash, status FROM generation_jobs "
            "WHERE owner_user_id = ? AND operation = ? AND idempotency_key = ?",
            (owner_user_id, operation, idempotency_key),
        ).fetchone()
        if existing:
            if existing["input_hash"] != digest:
                insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                                 idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                                 rejection_reason="idempotency_key_input_mismatch")
                conn.commit()
                raise GenerationControlError(409, "Idempotency-Key was already used with different input")
            return JobClaim(existing["id"], existing["episode_id"], duplicate=True, status=existing["status"])

        active = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs WHERE owner_user_id = ? AND status = 'active'",
            (owner_user_id,),
        ).fetchone()["count"]
        if active >= ACTIVE_LIMIT:
            insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                             idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                             rejection_reason="active_limit")
            conn.commit()
            raise GenerationControlError(429, "Another generation is already running", 60)

        daily = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs "
            "WHERE owner_user_id = ? AND claimed_at >= ? AND claimed_at < ?",
            (owner_user_id, day_start, day_end),
        ).fetchone()["count"]
        if daily >= DAILY_LIMIT:
            insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                             idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                             rejection_reason="daily_limit")
            conn.commit()
            raise GenerationControlError(429, "Daily generation limit exceeded", _seconds_until_jst_midnight(now))

        cursor = conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, claimed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (owner_user_id, operation, idempotency_key, digest, _utc_text(now)),
        )
        audit_id = insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result="started",
                                    idempotency_key_hash=key_digest, input_hash=digest,
                                    generation_job_id=cursor.lastrowid, accepted=True, started_at=_utc_text(now))
        episode_id = None
        if episode_date is not None:
            try:
                episode_id = _insert_episode(conn, episode_date, episode_type, source_url)
            except Exception:
                # 予約自体は監査済みなので、作成失敗も started/failure 対で確定する。
                insert_audit_log(
                    conn, operation=operation, actor_user_id=owner_user_id, result="failure",
                    idempotency_key_hash=key_digest, input_hash=digest,
                    generation_job_id=cursor.lastrowid, accepted=True,
                )
                conn.execute(
                    "UPDATE generation_jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (cursor.lastrowid,),
                )
                conn.commit()
                raise
            conn.execute("UPDATE generation_jobs SET episode_id = ? WHERE id = ?", (episode_id, cursor.lastrowid))
            conn.execute("UPDATE audit_logs SET episode_id = ? WHERE id = ?", (episode_id, audit_id))
        return JobClaim(cursor.lastrowid, episode_id, audit_id=audit_id)


def bind_episode(job_id: int, episode_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET episode_id = ? WHERE id = ?", (episode_id, job_id))
        conn.execute("UPDATE audit_logs SET episode_id = ? WHERE generation_job_id = ?", (episode_id, job_id))


def finish_job(job_id: int, success: bool) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE generation_jobs SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
            ("completed" if success else "failed", job_id),
        )
