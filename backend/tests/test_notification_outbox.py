import json
import os
from pathlib import Path
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
    assert json.loads(outbox[0]["payload"]) == {
        "url": f"/episodes/{episode_id}",
        "body": "番組の生成が完了しました",
    }
    assert len(deliveries) == 1


def test_non_radio_completion_does_not_enqueue_notification():
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-07-02", status="generating", type="commentary")
    assert EpisodeService().complete_radio_episode_with_notification(episode_id) is True

    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()["status"] == "completed"
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0


def test_synthesize_radio_completion_uses_outbox_completion_path(monkeypatch):
    from app.api.generate import SynthesizeRequest, _stream_synthesize
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService
    from app.services import telegram_notifier
    from unittest.mock import Mock

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat-id")
    from app.config import get_settings
    get_settings.cache_clear()

    service = EpisodeService()
    episode_id = service.create_episode("2099-07-07", status="completed", type="radio")
    base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
    base_dir.mkdir(parents=True)
    (base_dir / "script.json").write_text('{"lines": [{"text": "hello"}]}', encoding="utf-8")
    telegram_requests = []
    original_post = telegram_notifier.httpx.post

    def guarded_post(url, *args, **kwargs):
        if url.startswith("https://api.telegram.org/"):
            telegram_requests.append(url)
            return Mock()
        return original_post(url, *args, **kwargs)

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=1), \
         patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
         patch.object(telegram_notifier.httpx, "post", side_effect=guarded_post):
        list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))

    assert telegram_requests == []

    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()["status"] == "completed"
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox WHERE episode_id = ?", (episode_id,)).fetchone()[0] == 1


def test_synthesize_success_sends_telegram_notification_with_script_title_and_seq():
    from app.api.generate import SynthesizeRequest, _stream_synthesize
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id, seq = service.create_radio_episode("2099-07-08", status="completed")
    base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
    base_dir.mkdir(parents=True)
    (base_dir / "script.json").write_text(
        '{"title": "テスト番組 2099-07-08", "lines": [{"text": "hello"}]}',
        encoding="utf-8",
    )

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=1), \
         patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
         patch("app.api.generate.notify_success") as notify_success:
        list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))

    notify_success.assert_called_once_with(
        title="テスト番組 2099-07-08", episode_id=episode_id, seq=seq
    )


def test_synthesize_success_uses_daily_program_name_fallback_without_script_title():
    from app.api.generate import SynthesizeRequest, _stream_synthesize
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id, seq = service.create_radio_episode("2099-07-09", status="completed")
    base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
    base_dir.mkdir(parents=True)
    (base_dir / "script.json").write_text(
        '{"lines": [{"text": "hello"}]}', encoding="utf-8"
    )

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=1), \
         patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
         patch("app.api.generate.notify_success") as notify_success:
        list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))

    notify_success.assert_called_once_with(
        title="ニュースのとなり", episode_id=episode_id, seq=seq
    )


def test_synthesize_notification_failure_does_not_change_success():
    from app.api.generate import SynthesizeRequest, _stream_synthesize
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode("2099-07-10", status="completed", type="radio")
    base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
    base_dir.mkdir(parents=True)
    (base_dir / "script.json").write_text(
        '{"title": "通知テスト", "lines": [{"text": "hello"}]}',
        encoding="utf-8",
    )

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=1), \
         patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
         patch("app.api.generate.notify_success", side_effect=RuntimeError("offline")) as notify_success:
        events = list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))

    notify_success.assert_called_once()
    assert any(b"event: complete" in event for event in events)
    assert service.get_episode(episode_id)["status"] == "completed"


def test_synthesize_failure_does_not_send_telegram_notification():
    from app.api.generate import SynthesizeRequest, _stream_synthesize
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-07-11", status="completed", type="radio")
    base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
    base_dir.mkdir(parents=True)
    (base_dir / "script.json").write_text(
        '{"title": "失敗テスト", "lines": [{"text": "hello"}]}',
        encoding="utf-8",
    )

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=0), \
         patch("app.api.generate.notify_success") as notify_success:
        events = list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))

    notify_success.assert_not_called()
    assert any(b"event: error" in event for event in events)


def test_subscription_added_after_completion_is_not_added_to_delivery_rows(monkeypatch):
    from app.batch import deliver_notifications
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    monkeypatch.setenv("VAPID_CLAIMS_EMAIL", "owner@example.test")
    from app.config import get_settings
    get_settings.cache_clear()

    service = EpisodeService()
    episode_id = service.create_episode("2099-07-06", status="generating", type="radio")
    service.complete_radio_episode_with_notification(episode_id)
    _insert_subscription()

    with patch.object(deliver_notifications, "send_web_push") as send:
        stats = deliver_notifications.run_once()

    send.assert_not_called()
    assert stats["claimed"] == 0
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0] == 0


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
    assert send.call_args.args[0].payload == {
        "url": f"/episodes/{episode_id}",
        "body": "番組の生成が完了しました",
    }
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
