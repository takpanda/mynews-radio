#!/usr/bin/env python3
"""Deliver Web Push notifications from the durable SQLite outbox.

This is intentionally a short-lived cron command, not a resident worker.
"""

import json
import logging
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 60


class PushDeliveryError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Delivery:
    id: int
    endpoint: str
    p256dh: str
    auth: str
    payload: dict
    attempts: int


def send_web_push(delivery: Delivery) -> None:
    """Send one payload without logging endpoint or subscription keys."""
    settings = get_settings()
    if not settings.vapid_private_key or not settings.vapid_claims_email:
        raise PushDeliveryError("VAPID sender is not configured")

    from pywebpush import WebPushException, webpush

    claims_email = settings.vapid_claims_email
    if ":" not in claims_email:
        claims_email = f"mailto:{claims_email}"
    try:
        webpush(
            subscription_info={
                "endpoint": delivery.endpoint,
                "keys": {"p256dh": delivery.p256dh, "auth": delivery.auth},
            },
            data=json.dumps(delivery.payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": claims_email},
        )
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        raise PushDeliveryError("Web Push request failed", status_code) from exc
    except Exception as exc:
        raise PushDeliveryError("Web Push request failed") from exc


def _ensure_delivery_rows() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO notification_deliveries (outbox_id, subscription_id)
            SELECT o.id, s.id
            FROM notification_outbox o
            JOIN push_subscriptions s ON s.is_active = 1
            LEFT JOIN notification_deliveries d
              ON d.outbox_id = o.id AND d.subscription_id = s.id
            WHERE d.id IS NULL
            """
        )
        # A process killed during a request must not leave a delivery stuck forever.
        conn.execute(
            """
            UPDATE notification_deliveries
            SET status = 'pending', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'sending'
              AND updated_at < datetime('now', '-10 minutes')
            """
        )


def _claim_delivery() -> Delivery | None:
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT d.id, d.attempts, s.endpoint, s.p256dh, s.auth, o.payload
            FROM notification_deliveries d
            JOIN push_subscriptions s ON s.id = d.subscription_id AND s.is_active = 1
            JOIN notification_outbox o ON o.id = d.outbox_id
            WHERE d.status = 'pending' AND d.next_attempt_at <= CURRENT_TIMESTAMP
            ORDER BY d.id
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        changed = conn.execute(
            "UPDATE notification_deliveries SET status = 'sending', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'",
            (row["id"],),
        ).rowcount
        if not changed:
            return None
        return Delivery(
            id=row["id"],
            endpoint=row["endpoint"],
            p256dh=row["p256dh"],
            auth=row["auth"],
            payload=json.loads(row["payload"]),
            attempts=row["attempts"],
        )


def _mark_success(delivery_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE notification_deliveries SET status = 'sent', sent_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (delivery_id,),
        )


def _mark_failure(delivery: Delivery, error: PushDeliveryError) -> bool:
    attempts = delivery.attempts + 1
    permanent = error.status_code in {404, 410}
    terminal = permanent or attempts >= MAX_ATTEMPTS
    status = "discarded" if permanent else ("failed" if terminal else "pending")
    with get_db_connection() as conn:
        if permanent:
            conn.execute(
                "UPDATE push_subscriptions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT subscription_id FROM notification_deliveries WHERE id = ?)",
                (delivery.id,),
            )
        conn.execute(
            """
            UPDATE notification_deliveries
            SET status = ?, attempts = ?,
                next_attempt_at = datetime('now', ?),
                last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                attempts,
                f"+{BACKOFF_SECONDS * (2 ** max(0, attempts - 1))} seconds",
                str(error)[:200],
                delivery.id,
            ),
        )
    return terminal


def run_once() -> dict[str, int]:
    settings = get_settings()
    if not settings.vapid_private_key or not settings.vapid_claims_email:
        logger.warning("Web Push delivery skipped: VAPID sender is not configured")
        return {"claimed": 0, "success": 0, "failed": 0, "disabled": 0}

    _ensure_delivery_rows()
    stats = {"claimed": 0, "success": 0, "failed": 0, "disabled": 0}
    while True:
        delivery = _claim_delivery()
        if delivery is None:
            break
        stats["claimed"] += 1
        try:
            send_web_push(delivery)
            _mark_success(delivery.id)
            stats["success"] += 1
        except PushDeliveryError as exc:
            terminal = _mark_failure(delivery, exc)
            stats["failed"] += 1
            if exc.status_code in {404, 410}:
                stats["disabled"] += 1
            logger.warning("Web Push delivery failed: status=%s terminal=%s", exc.status_code, terminal)
    logger.info(
        "Web Push delivery complete: claimed=%d success=%d failed=%d disabled=%d",
        stats["claimed"], stats["success"], stats["failed"], stats["disabled"],
    )
    return stats


def main() -> None:
    from app.logging_config import setup_daily_logging
    setup_daily_logging(__name__, level=logging.INFO)
    run_once()


if __name__ == "__main__":
    main()
