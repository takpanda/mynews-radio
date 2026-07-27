import json
from unittest.mock import patch


def _insert_subscription():
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        return conn.execute(
            """
            INSERT INTO push_subscriptions
                (subscription_id_hash, endpoint_hash, endpoint, p256dh, auth)
            VALUES ('sid', 'eid', 'https://push.example.test/send/token', 'p256dh', 'auth')
            """
        ).lastrowid


def test_radio_completion_enqueues_one_outbox_event_in_same_transaction():
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode("2099-07-01", status="generating", type="radio")
    _insert_subscription()

    assert service.complete_radio_episode_with_notification(episode_id) is True
    assert service.complete_radio_episode_with_notification(episode_id) is True

    with get_db_connection() as conn:
        episode = conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        outbox = conn.execute(
            "SELECT event_type, episode_id, payload FROM notification_outbox WHERE episode_id = ?",
            (episode_id,),
        ).fetchall()
        deliveries = conn.execute("SELECT status FROM notification_deliveries").fetchall()

    assert episode["status"] == "completed"
    assert len(outbox) == 1
    assert outbox[0]["event_type"] == "daily_radio_completed"
    assert json.loads(outbox[0]["payload"]) == {"url": f"/episodes/{episode_id}"}
    assert len(deliveries) == 1


def test_non_radio_completion_does_not_enqueue_notification():
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-07-02", status="generating", type="commentary")
    assert EpisodeService().complete_radio_episode_with_notification(episode_id) is False

    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()["status"] == "generating"
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0


def test_delivery_success_and_payload_does_not_include_article_title(monkeypatch):
    from app.batch import deliver_notifications
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "owner@example.test")
    from app.config import get_settings
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-07-03", status="generating", type="radio")
    _insert_subscription()
    EpisodeService().complete_radio_episode_with_notification(episode_id)

    with patch.object(deliver_notifications, "send_web_push") as send:
        stats = deliver_notifications.run_once()

    send.assert_called_once()
    assert send.call_args.args[0].payload == {"url": f"/episodes/{episode_id}"}
    assert stats["success"] == 1
    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM notification_deliveries").fetchone()["status"] == "sent"


def test_410_disables_subscription_and_does_not_retry(monkeypatch):
    from app.batch import deliver_notifications
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "owner@example.test")
    from app.config import get_settings
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-07-04", status="generating", type="radio")
    subscription_id = _insert_subscription()
    EpisodeService().complete_radio_episode_with_notification(episode_id)

    error = deliver_notifications.PushDeliveryError("gone", 410)
    with patch.object(deliver_notifications, "send_web_push", side_effect=error):
        stats = deliver_notifications.run_once()

    assert stats["disabled"] == 1
    with get_db_connection() as conn:
        assert conn.execute("SELECT is_active FROM push_subscriptions WHERE id = ?", (subscription_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT status, attempts FROM notification_deliveries").fetchone()["status"] == "discarded"


def test_transient_failure_retries_at_most_three_times(monkeypatch):
    from app.batch import deliver_notifications
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "owner@example.test")
    from app.config import get_settings
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-07-05", status="generating", type="radio")
    _insert_subscription()
    EpisodeService().complete_radio_episode_with_notification(episode_id)
    deliver_notifications.BACKOFF_SECONDS = 0

    with patch.object(
        deliver_notifications,
        "send_web_push",
        side_effect=deliver_notifications.PushDeliveryError("temporary", 503),
    ):
        stats = deliver_notifications.run_once()

    assert stats["claimed"] == 3
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, attempts FROM notification_deliveries").fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 3
