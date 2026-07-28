"""オーナー操作の監査ログ。機密情報や認証トークンは保存しない。"""

from datetime import datetime, timezone
from typing import Optional

from app.db.connection import get_db_connection


def record_audit_log(operation: str, owner_user_id: Optional[int], result: str, episode_id: Optional[int] = None) -> None:
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (operation, owner_user_id, executed_at, result, episode_id) VALUES (?, ?, ?, ?, ?)",
                (operation, owner_user_id, datetime.now(timezone.utc).isoformat(), result, episode_id),
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("failed to write audit log")
