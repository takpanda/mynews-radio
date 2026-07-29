"""生成操作の監査ログ。機密情報や認証トークンは保存しない。"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db.connection import get_db_connection


logger = logging.getLogger(__name__)


def hash_idempotency_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_audit_log(
    operation: str,
    owner_user_id: Optional[int],
    result: str,
    episode_id: Optional[int] = None,
    *,
    idempotency_key: Optional[str] = None,
    input_hash: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> None:
    """1イベントを記録する。DB失敗は握りつぶさず呼び出し元へ返す。"""
    now = datetime.now(timezone.utc).isoformat()
    accepted = 0 if result == "rejected" else 1
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO audit_logs
               (operation, owner_user_id, actor_user_id, executed_at, result,
                accepted, rejection_reason, idempotency_key_hash, input_hash,
                started_at, finished_at, episode_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (operation, owner_user_id, owner_user_id, now, result, accepted,
             rejection_reason, hash_idempotency_key(idempotency_key), input_hash,
             now if result == "started" else None,
             now if result in {"success", "failure", "rejected"} else None,
             episode_id),
        )


def delete_expired_audit_logs(retention_days: int = 90, now: Optional[datetime] = None) -> int:
    """保持期間を超えた監査ログを削除し、削除件数を返す。"""
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=retention_days)).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM audit_logs WHERE COALESCE(finished_at, started_at, executed_at) < ?",
            (cutoff,),
        )
        return cursor.rowcount
