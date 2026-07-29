"""生成操作の監査ログ。機密情報や認証トークンは保存しない。"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.connection import get_db_connection


RETENTION_DAYS = 90


def hash_value(value: str) -> str:
    """監査用の一方向ハッシュ。キー本文やトークンを保存しない。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_input(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hash_value(encoded)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_audit_log(
    conn,
    *,
    operation: str,
    actor_user_id: Optional[int],
    result: str,
    idempotency_key_hash: Optional[str] = None,
    input_hash: Optional[str] = None,
    episode_id: Optional[int] = None,
    generation_job_id: Optional[int] = None,
    accepted: bool = True,
    rejection_reason: Optional[str] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> int:
    now = _now()
    cursor = conn.execute(
        "INSERT INTO audit_logs "
        "(operation, owner_user_id, actor_user_id, generation_job_id, idempotency_key_hash, input_hash, "
        " executed_at, result, accepted, rejection_reason, started_at, ended_at, episode_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (operation, actor_user_id, actor_user_id, generation_job_id, idempotency_key_hash, input_hash,
         now, result, int(accepted), rejection_reason, started_at or (now if result == "started" else None),
         ended_at or (now if result in {"success", "failure", "rejected"} else None), episode_id),
    )
    return int(cursor.lastrowid)


def record_audit_log(operation: str, owner_user_id: Optional[int], result: str, episode_id: Optional[int] = None) -> None:
    """後方互換用の監査記録。書込み失敗は呼び出し元へ返す。"""
    with get_db_connection() as conn:
        insert_audit_log(conn, operation=operation, actor_user_id=owner_user_id, result=result, episode_id=episode_id,
                         accepted=result != "rejected")


def finalize_audit_log(job_id: int, result: str, episode_id: Optional[int]) -> None:
    """受付時のハッシュを引き継いだ終了イベントを記録する。"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT operation, actor_user_id, idempotency_key_hash, input_hash "
            "FROM audit_logs WHERE generation_job_id = ? AND result = 'started' ORDER BY id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("audit start record not found")
        insert_audit_log(
            conn, operation=row["operation"], actor_user_id=row["actor_user_id"], result=result,
            idempotency_key_hash=row["idempotency_key_hash"], input_hash=row["input_hash"],
            generation_job_id=job_id, episode_id=episode_id, accepted=True,
        )


def cleanup_audit_logs() -> int:
    """90日を超えた監査ログを1トランザクションで削除する。"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM audit_logs WHERE executed_at < datetime('now', ?)",
            (f"-{RETENTION_DAYS} days",),
        )
        return cursor.rowcount
