"""管理者セッション専用の生成監査ログ閲覧API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_owner_session
from app.db.connection import get_db_connection

router = APIRouter(tags=["admin-audit"])


@router.get("/admin/audit-logs", summary="生成監査ログを取得")
def list_audit_logs(
    _: Annotated[int, Depends(require_owner_session)],
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    """管理者セッション利用者だけに監査情報を返す（秘密値はハッシュのみ）。"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, operation, actor_user_id, episode_id, idempotency_key_hash, input_hash, "
            "accepted, result, rejection_reason, started_at, ended_at "
            "FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
