"""台本確認待ちへの遷移と通知Outbox登録。"""

import json

from app.db.connection import get_db_connection


def move_episode_to_awaiting_review(episode_id: int, reason: str) -> bool:
    """確認待ちへ遷移し、遷移ごとに一意なPush通知を登録する。

    既に確認待ちの場合は画面再読込・再チェック等による重複通知を抑止する。
    """
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, review_cycle FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        if row is None or row["status"] == "awaiting_review":
            return False

        cycle = row["review_cycle"] + 1
        conn.execute(
            "UPDATE episodes SET status='awaiting_review', phase='awaiting_review', "
            "generation_message=?, review_cycle=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reason, cycle, episode_id),
        )
        event_type = f"script_awaiting_review:{cycle}"
        payload = json.dumps({
            "url": f"/admin/episodes/{episode_id}/review",
            "title": "台本の確認待ちがあります",
            "body": "確認待ちの台本があります",
        }, ensure_ascii=False)
        outbox = conn.execute(
            "INSERT INTO notification_outbox(event_type, episode_id, payload) VALUES (?, ?, ?)",
            (event_type, episode_id, payload),
        )
        conn.execute(
            "INSERT INTO notification_deliveries(outbox_id, subscription_id) "
            "SELECT ?, id FROM push_subscriptions WHERE is_active=1 AND admin_user_id IS NOT NULL",
            (outbox.lastrowid,),
        )
        return True
