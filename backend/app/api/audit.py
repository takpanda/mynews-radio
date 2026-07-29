"""管理者専用の生成監査ログ参照API。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth import require_owner_session
from app.db.connection import get_db_connection

router = APIRouter(prefix="/admin", tags=["audit"])


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    operation: Optional[str] = Query(None),
    _owner_user_id: int = Depends(require_owner_session),
) -> list[dict]:
    query = (
        "SELECT id, operation, owner_user_id, actor_user_id, episode_id, result, "
        "accepted, rejection_reason, idempotency_key_hash, input_hash, "
        "started_at, finished_at, executed_at FROM audit_logs"
    )
    params: list[object] = []
    if operation:
        query += " WHERE operation = ?"
        params.append(operation)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
