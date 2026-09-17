"""永続化された生成キューと冪等性・監査制御。"""

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.audit import hash_value, insert_audit_log
from app.config import get_settings
from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

STALE_ACTIVE_TIMEOUT = timedelta(minutes=10)
IDEMPOTENCY_RETENTION = timedelta(hours=24)
MAX_QUEUED_JOBS = 3
SYSTEM_OWNER_USERNAME = "__generation_queue_system__"


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
    payload: object | None = None


def input_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configured_queue_limit() -> int:
    value = getattr(get_settings(), "max_queued_jobs", MAX_QUEUED_JOBS)
    return max(0, int(value))


def _is_system_owner(conn, owner_user_id: int) -> bool:
    row = conn.execute("SELECT username FROM admin_users WHERE id = ?", (owner_user_id,)).fetchone()
    return bool(row and row["username"] == SYSTEM_OWNER_USERNAME)


def _insert_episode(conn, episode_date: str, episode_type: str, source_url: str | None, status: str) -> int:
    if episode_type == "radio":
        if status == "active":
            conn.execute(
                "UPDATE episodes SET status = 'failed', updated_at = CURRENT_TIMESTAMP "
                "WHERE episode_date = ? AND type = 'radio' AND status = 'generating'",
                (episode_date,),
            )
        cursor = conn.execute(
            "INSERT INTO episodes (episode_date, seq, status, type) "
            "SELECT ?, COALESCE(MAX(seq), -1) + 1, ?, 'radio' "
            "FROM episodes WHERE episode_date = ? AND type = 'radio'",
            (episode_date, status, episode_date),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO episodes (episode_date, status, type, source_url) VALUES (?, ?, ?, ?)",
            (episode_date, status, episode_type, source_url),
        )
    return int(cursor.lastrowid)


def enqueue_job(
    owner_user_id: int,
    operation: str,
    idempotency_key: str,
    payload: object,
    *,
    episode_date: str | None = None,
    episode_type: str = "radio",
    source_url: str | None = None,
    episode_id: int | None = None,
    client_ip: str = "unknown",
    dispatch: bool = False,
) -> JobClaim:
    """ジョブをFIFOへ登録する。同時実行中ならwaitingとして永続化する。"""
    digest = input_hash(payload)
    key_digest = hash_value(idempotency_key) if idempotency_key else None
    client_ip_digest = hash_value(client_ip or "unknown")
    if not idempotency_key or len(idempotency_key) > 255:
        with get_db_connection() as conn:
            insert_audit_log(
                conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                rejection_reason="invalid_idempotency_key",
            )
        raise GenerationControlError(400, "Idempotency-Key is required and must be at most 255 characters")

    now = _utc_now()
    retention_cutoff = _utc_text(now - IDEMPOTENCY_RETENTION)
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        stale_cutoff = _utc_text(now - STALE_ACTIVE_TIMEOUT)
        conn.execute(
            "UPDATE generation_jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP "
            "WHERE status = 'active' AND claimed_at < ?",
            (stale_cutoff,),
        )
        conn.execute(
            "DELETE FROM generation_jobs WHERE claimed_at < ? AND status != 'waiting'",
            (retention_cutoff,),
        )
        existing = conn.execute(
            "SELECT id, episode_id, input_hash, status, payload FROM generation_jobs "
            "WHERE owner_user_id = ? AND operation = ? AND idempotency_key = ?",
            (owner_user_id, operation, idempotency_key),
        ).fetchone()
        if existing:
            if existing["input_hash"] != digest:
                insert_audit_log(
                    conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                    idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                    rejection_reason="idempotency_key_input_mismatch",
                )
                conn.commit()
                raise GenerationControlError(409, "Idempotency-Key was already used with different input")
            return JobClaim(
                existing["id"], existing["episode_id"], duplicate=True,
                status=existing["status"], payload=json.loads(existing["payload"] or "{}"),
            )

        active_count = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs WHERE status = 'active'"
        ).fetchone()["count"]
        queued_count = conn.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs j "
            "LEFT JOIN admin_users u ON u.id = j.owner_user_id "
            "WHERE j.status = 'waiting' AND (u.username IS NULL OR u.username != ?)",
            (SYSTEM_OWNER_USERNAME,),
        ).fetchone()["count"]
        system_owner = _is_system_owner(conn, owner_user_id)
        if active_count or queued_count:
            status = "waiting"
            if not system_owner and queued_count >= _configured_queue_limit():
                insert_audit_log(
                    conn, operation=operation, actor_user_id=owner_user_id, result="rejected",
                    idempotency_key_hash=key_digest, input_hash=digest, accepted=False,
                    rejection_reason="queued_limit",
                )
                conn.commit()
                raise GenerationControlError(429, "Generation queue is full", 60)
        else:
            status = "active"

        cursor = conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, "
            "client_ip_hash, payload, status, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_user_id, operation, idempotency_key, digest, client_ip_digest, payload_text,
             status, _utc_text(now)),
        )
        job_id = int(cursor.lastrowid)
        audit_id = insert_audit_log(
            conn, operation=operation, actor_user_id=owner_user_id, result="started",
            idempotency_key_hash=key_digest, input_hash=digest, generation_job_id=job_id,
            accepted=True, started_at=_utc_text(now) if status == "active" else None,
        )
        reserved_episode_id = episode_id
        if episode_date is not None:
            try:
                reserved_episode_id = _insert_episode(conn, episode_date, episode_type, source_url, status)
            except Exception:
                insert_audit_log(
                    conn, operation=operation, actor_user_id=owner_user_id, result="failure",
                    idempotency_key_hash=key_digest, input_hash=digest,
                    generation_job_id=job_id, accepted=True,
                )
                conn.execute(
                    "UPDATE generation_jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (job_id,),
                )
                conn.commit()
                raise
        if reserved_episode_id is not None:
            conn.execute("UPDATE generation_jobs SET episode_id = ? WHERE id = ?", (reserved_episode_id, job_id))
            conn.execute("UPDATE audit_logs SET episode_id = ? WHERE id = ?", (reserved_episode_id, audit_id))
            if episode_date is None:
                conn.execute(
                    "UPDATE episodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("generating" if status == "active" else "waiting", reserved_episode_id),
                )
        claim = JobClaim(job_id, reserved_episode_id, status=status, audit_id=audit_id, payload=payload)

    if dispatch:
        _dispatcher.notify(job_id)
    return claim


def claim_job(*args, **kwargs) -> JobClaim:
    """後方互換名。新規コードではenqueue_jobを使用する。"""
    return enqueue_job(*args, **kwargs)


def promote_next_job() -> JobClaim | None:
    """activeが無い場合だけ最古のwaitingを条件付きUPDATEで昇格する。"""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM generation_jobs WHERE status = 'active' LIMIT 1").fetchone():
            return None
        row = conn.execute(
            "SELECT id, episode_id, payload FROM generation_jobs "
            "WHERE status = 'waiting' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        changed = conn.execute(
            "UPDATE generation_jobs SET status = 'active', claimed_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'waiting'", (row["id"],)
        )
        if changed.rowcount != 1:
            return None
        if row["episode_id"] is not None:
            conn.execute(
                "UPDATE episodes SET status = 'generating', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'waiting'", (row["episode_id"],)
            )
        conn.execute(
            "UPDATE audit_logs SET started_at = CURRENT_TIMESTAMP, episode_id = COALESCE(episode_id, ?) "
            "WHERE generation_job_id = ? AND result = 'started'",
            (row["episode_id"], row["id"]),
        )
        return JobClaim(
            row["id"], row["episode_id"], status="active",
            payload=json.loads(row["payload"] or "{}"),
        )


def promote_next_waiting_job() -> JobClaim | None:
    """条件付きFIFO昇格の明示的なAPI名。"""
    return promote_next_job()


def finish_job(job_id: int, success: bool) -> None:
    """activeジョブを終端化し、次の待機ジョブへ処理を渡す。"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE generation_jobs SET status = ?, finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'active'",
            ("completed" if success else "failed", job_id),
        )
    _dispatcher.notify()


def bind_episode(job_id: int, episode_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE generation_jobs SET episode_id = ? WHERE id = ?", (episode_id, job_id))
        conn.execute("UPDATE audit_logs SET episode_id = ? WHERE generation_job_id = ?", (episode_id, job_id))


def recover_generation_queue() -> None:
    """プロセス再起動時に前プロセスのactiveを失敗扱いにし、waitingを復旧する。

    activeはプロセス内ワーカーの所有権を表すため、起動したプロセスから
    引き継げる実行主体は存在しない。ここでは経過時間にかかわらず残留行を
    orphanとして扱い、FIFOを止めない。
    """
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE generation_jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP "
            "WHERE status = 'active'"
        )
    _dispatcher.notify()


def dispatch_job(job_id: int | None = None) -> None:
    """コミット済みジョブをディスパッチャへ通知する。"""
    # episodeを持たない低レベル予約は実行経路を持たないため、FIFOの
    # 状態検証用途として保持する。API/cronの実ジョブは必ずepisodeを持つ。
    with get_db_connection() as conn:
        unbound_active = conn.execute(
            "SELECT 1 FROM generation_jobs WHERE status = 'active' "
            "AND episode_id IS NULL AND operation != 'daily' LIMIT 1"
        ).fetchone()
    if unbound_active:
        return
    _dispatcher.notify(job_id)


class GenerationDispatcher:
    """DBを正とする単一ワーカーのディスパッチャ。"""

    def __init__(self):
        self._condition = threading.Condition()
        self._requested: set[int] = set()
        self._thread: threading.Thread | None = None

    def notify(self, job_id: int | None = None) -> None:
        with self._condition:
            if job_id is not None:
                self._requested.add(job_id)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="generation-dispatcher", daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception:
            # DBの切替・停止中にワーカーが追いついた場合は、次回enqueue
            # またはプロセス起動時の復旧で再度確認する。
            logger.exception("generation dispatcher stopped unexpectedly")
            with self._condition:
                self._thread = None

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                job_id = self._requested.pop() if self._requested else None
            if job_id is None:
                promoted = promote_next_job()
                if promoted is not None:
                    job_id = promoted.job_id
                else:
                    with get_db_connection() as conn:
                        waiting = conn.execute("SELECT 1 FROM generation_jobs WHERE status = 'waiting' LIMIT 1").fetchone()
                    if waiting:
                        with self._condition:
                            self._condition.wait(timeout=0.2)
                        continue
                    with self._condition:
                        self._thread = None
                    return
            try:
                with get_db_connection() as conn:
                    job = conn.execute(
                        "SELECT * FROM generation_jobs WHERE id = ? AND status = 'active'", (job_id,)
                    ).fetchone()
                if job:
                    # payloadだけを扱う制御テストや外部利用者の予約を、API実行
                    # 経路として誤って実行しない。実ジョブはepisodeを予約する。
                    if job["episode_id"] is None and job["operation"] != "daily":
                        continue
                    self._execute(job)
            except Exception:
                logger.exception("generation job dispatch failed: job_id=%d", job_id)
                try:
                    with get_db_connection() as conn:
                        row = conn.execute("SELECT episode_id FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
                    if row and row["episode_id"] is not None:
                        from app.services.episode_service import EpisodeService
                        EpisodeService().update_episode_status(row["episode_id"], "failed")
                finally:
                    finish_job(job_id, False)

    @staticmethod
    def _execute(job) -> None:
        from app.api.generate import execute_queued_job
        execute_queued_job(job)


_dispatcher = GenerationDispatcher()
