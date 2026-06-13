import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import sqlite3

from app.db.connection import get_db_connection

def retry_on_busy(max_retries: int = 5, initial_delay: float = 0.1):
    """Retries a database operation on sqlite3.OperationalError (database is locked)."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and retries < max_retries:
                        time.sleep(initial_delay * (2**retries))
                        retries += 1
                    else:
                        raise
        return wrapper
    return decorator

class EpisodeService:
    @retry_on_busy()
    def create_episode(
        self,
        episode_date: str,
        script_text: Optional[str] = None,
        audio_path: Optional[str] = None,
        status: str = "pending",
    ) -> int:
        """エピソードを新規作成し、id を返す"""
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO episodes (episode_date, script_text, audio_path, status)
                VALUES (?, ?, ?, ?)
                """,
                (episode_date, script_text, audio_path, status),
            )
            return cursor.lastrowid

    @retry_on_busy()
    def update_episode_status(self, episode_id: int, status: str) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, episode_id),
            )

    @retry_on_busy()
    def update_episode_phase(self, episode_id: int, phase: str, message: Optional[str] = None) -> None:
        """Updates the progress phase for an episode. Optionally updates generation_message too."""
        with get_db_connection() as conn:
            if message is not None:
                conn.execute(
                    """
                    UPDATE episodes
                    SET phase = ?, generation_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (phase, message, episode_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE episodes
                    SET phase = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (phase, episode_id),
                )

    @retry_on_busy()
    def add_episode_item(
        self,
        episode_id: int,
        article_id: Optional[int],
        item_order: int,
        segment_text: str,
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO episode_items (episode_id, article_id, item_order, segment_text)
                VALUES (?, ?, ?, ?)
                """,
                (episode_id, article_id, item_order, segment_text),
            )

    def get_episode_list(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, episode_date, audio_path, status
                FROM episodes
                ORDER BY episode_date DESC, id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_episode(self) -> Optional[dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM episodes
                ORDER BY episode_date DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    @retry_on_busy()
    def get_generating_episode(self, episode_date: str) -> Optional[int]:
        """同一日かつ status=\"generating\" のエピソードを検索し、id を返す。存在しない場合は None"""
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM episodes
                WHERE episode_date = ? AND status = 'generating'
                LIMIT 1
                """,
                (episode_date,),
            ).fetchone()
            return row["id"] if row else None

    def get_episode(self, episode_id: int) -> Optional[dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_episode_items(self, episode_id: int) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM episode_items
                WHERE episode_id = ?
                ORDER BY item_order ASC
                """,
                (episode_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_episode_audio_path(self, episode_id: int) -> Optional[str]:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT audio_path FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            return row["audio_path"] if row else None

    def find_generating_by_date(self, episode_date: str) -> Optional[int]:
        """Find an episode id with the given date and status 'generating'. Returns None if not found."""
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM episodes WHERE episode_date = ? AND status = 'generating' LIMIT 1",
                (episode_date,),
            ).fetchone()
            return row["id"] if row else None

    @retry_on_busy()
    def claim_generating_slot(self, episode_id: int) -> bool:
        """Atomically change status from 'pending' to 'generating'.

        Returns True if the episode was in 'pending' and is now 'generating'.
        Returns False if the row did not match (status was not 'pending').
        """
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE episodes
                SET status = 'generating', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (episode_id,),
            )
            return cursor.rowcount > 0

    @retry_on_busy()
    def reset_episode_for_reuse(self, episode_id: int) -> None:
        """Reset a stale episode's status and phase for reuse."""
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status = 'pending', phase = '', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (episode_id,),
            )

    @retry_on_busy()
    def clear_episode_items(self, episode_id: int) -> None:
        """Clear all episode_items for an episode."""
        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM episode_items WHERE episode_id = ?",
                (episode_id,),
            )

    @retry_on_busy()
    def update_episode_audio_path(self, episode_id: int, audio_path: str) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET audio_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (audio_path, episode_id),
            )

    def get_expired_episodes(self, retention_days: int) -> list[dict[str, Any]]:
        """保持期間を超過したエピソードの一覧を取得する"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, episode_date, status
                FROM episodes
                WHERE episode_date < ?
                ORDER BY episode_date ASC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(row) for row in rows]

    @retry_on_busy()
    def delete_episode(self, episode_id: int) -> bool:
        """エピソードと関連するepisode_itemsを削除し、レコードが存在した場合はTrueを返す"""
        with get_db_connection() as conn:
            row = conn.execute("SELECT id FROM episodes WHERE id = ?", (episode_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM episode_items WHERE episode_id = ?", (episode_id,))
            conn.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
            return True

