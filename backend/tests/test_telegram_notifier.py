from unittest.mock import Mock, patch


def test_success_message_contains_required_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-not-logged")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1004344317656")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services import telegram_notifier

    response = Mock()
    with patch.object(telegram_notifier.httpx, "post", return_value=response) as post:
        assert telegram_notifier.notify_success(title="テックニュース 2099-01-01 #2", episode_id=42, seq=2)
    response.raise_for_status.assert_called_once_with()
    body = post.call_args.kwargs["json"]
    assert "テックニュース 2099-01-01 #2" in body["text"]
    assert "エピソード番号: 2" in body["text"]
    assert "https://radio.beeworks.cc/episodes/42" in body["text"]


def test_failure_message_redacts_secrets_and_truncates(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services import telegram_notifier

    response = Mock()
    with patch.object(telegram_notifier.httpx, "post", return_value=response) as post:
        assert telegram_notifier.notify_failure(
            episode_id=7,
            phase="synthesize",
            error="api_key=super-secret " + "x" * 500,
        )
    text = post.call_args.kwargs["json"]["text"]
    assert "super-secret" not in text
    assert len(text) < 400
    assert "失敗工程: synthesize" in text


def test_notification_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services import telegram_notifier

    with patch.object(telegram_notifier.httpx, "post", side_effect=RuntimeError("secret")):
        assert telegram_notifier.notify_failure(episode_id=1, phase="build", error="safe") is False


def test_pipeline_failure_notifies_once_and_keeps_failed_status(monkeypatch):
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-01-01", status="generating", type="radio")
    failure = Mock()
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(side_effect=RuntimeError("secret")))
    monkeypatch.setattr(radio_pipeline, "notify_failure", failure)

    assert radio_pipeline.run_radio_pipeline(episode_id, episode_date="2099-01-01") is None
    assert failure.call_count == 1
    assert EpisodeService().get_episode(episode_id)["status"] == "failed"
