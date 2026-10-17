from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


def test_success_message_contains_required_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-not-logged")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat-id")
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
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat-id")
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
    failure = Mock(side_effect=RuntimeError("notification unavailable"))
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(side_effect=RuntimeError("secret")))
    monkeypatch.setattr(radio_pipeline, "notify_failure", failure)

    assert radio_pipeline.run_radio_pipeline(episode_id, episode_date="2099-01-01") is None
    assert failure.call_count == 1
    assert EpisodeService().get_episode(episode_id)["status"] == "failed"


def test_pipeline_notifies_when_new_articles_have_no_summaries(monkeypatch, tmp_path, caplog):
    from app.batch import radio_pipeline
    from app.batch.radio_pipeline import PipelineResult
    from app.services.article_service import ArticleService
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-01-03", status="generating", type="radio")
    failure = Mock()
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(return_value=(1, 0)))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", Mock(return_value=0))
    monkeypatch.setattr(radio_pipeline, "generate_script", Mock(return_value=0))
    monkeypatch.setattr(radio_pipeline, "notify_failure", failure)
    monkeypatch.setattr(ArticleService, "fetch_summaries_for_script", Mock(return_value=[]))

    with caplog.at_level("WARNING"):
        result = radio_pipeline.run_radio_pipeline(
            episode_id,
            episode_date="2099-01-03",
            default_episodes_dir=str(tmp_path),
        )

    assert result is PipelineResult.NO_CONTENT
    failure.assert_called_once_with(
        episode_id=episode_id,
        phase="summarize",
        error="新規記事の要約に成功しませんでした",
    )
    assert "新規記事の要約成功件数が0件" in caplog.text
    assert "No new articles to summarize" not in caplog.text
    assert EpisodeService().get_episode(episode_id) is None


def test_pipeline_does_not_notify_when_no_new_articles_were_imported(monkeypatch, tmp_path):
    from app.batch import radio_pipeline
    from app.batch.radio_pipeline import PipelineResult
    from app.services.article_service import ArticleService
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-01-04", status="generating", type="radio")
    failure = Mock()
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(return_value=(0, 1)))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", Mock(return_value=0))
    monkeypatch.setattr(radio_pipeline, "generate_script", Mock(return_value=0))
    monkeypatch.setattr(radio_pipeline, "notify_failure", failure)
    monkeypatch.setattr(ArticleService, "fetch_summaries_for_script", Mock(return_value=[]))

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-01-04",
        default_episodes_dir=str(tmp_path),
    )

    assert result is PipelineResult.NO_CONTENT
    failure.assert_not_called()
    assert EpisodeService().get_episode(episode_id) is None


@pytest.mark.parametrize("followup_failure", ["script_revision", "final_validation"])
def test_pipeline_suppresses_followup_failure_notification_after_summary_failure(
    monkeypatch, tmp_path, followup_failure
):
    from app.batch import radio_pipeline
    from app.db.connection import get_db_connection as real_get_db_connection
    from app.services.article_service import ArticleService
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode("2099-01-05", status="generating", type="radio")
    with real_get_db_connection() as conn:
        conn.execute("UPDATE episodes SET review_mode='auto' WHERE id=?", (episode_id,))

    def write_script(path, **_kwargs):
        from pathlib import Path

        script_path = Path(path)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text('{"style":"solo","lines":[{"text":"台本"}]}', encoding="utf-8")
        return 1

    if followup_failure == "script_revision":
        @contextmanager
        def fail_revision_insert():
            with real_get_db_connection() as conn:
                class ConnectionProxy:
                    def execute(self, sql, params=()):
                        if sql.lstrip().upper().startswith("INSERT INTO SCRIPT_REVISIONS"):
                            raise RuntimeError("simulated revision persistence failure")
                        return conn.execute(sql, params)

                yield ConnectionProxy()

        monkeypatch.setattr(radio_pipeline, "get_db_connection", fail_revision_insert)

    failure = Mock()
    monkeypatch.setattr(radio_pipeline, "notify_failure", failure)
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(return_value=(1, 0)))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", Mock(return_value=0))
    monkeypatch.setattr(
        ArticleService,
        "fetch_summaries_for_script",
        Mock(return_value=[{"id": 1, "article_id": 1, "title": "既存記事", "summary": "既存要約", "importance_score": 5}]),
    )
    monkeypatch.setattr(radio_pipeline, "generate_script", write_script)
    monkeypatch.setattr(radio_pipeline, "override_script_title", Mock())
    monkeypatch.setattr(radio_pipeline, "review_script", Mock(return_value={"revised": False, "review_count": 0}))
    monkeypatch.setattr(radio_pipeline, "should_run_final_validation", Mock(return_value=True))
    monkeypatch.setattr(
        radio_pipeline,
        "validate_final_script_file",
        Mock(return_value={"can_synthesize": False, "critical_issues": [{"message": "検証失敗"}], "warnings": []}),
    )

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-01-05",
        default_episodes_dir=str(tmp_path),
    )

    assert result is None
    failure.assert_called_once_with(
        episode_id=episode_id,
        phase="summarize",
        error="新規記事の要約に成功しませんでした",
    )
    assert service.get_episode(episode_id)["status"] == "failed"


def test_radio_pipeline_success_keeps_completed_when_notification_raises(monkeypatch, tmp_path):
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-01-02", status="generating", type="radio")
    episode_dir = tmp_path / str(episode_id)
    success = Mock(side_effect=RuntimeError("notification unavailable"))

    def write_script(path, **_kwargs):
        path_obj = __import__("pathlib").Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text('{"title":"テスト番組","lines":[{"text":"hello"}]}', encoding="utf-8")
        return 1

    monkeypatch.setattr(radio_pipeline, "notify_success", success)
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", Mock(return_value=(1, 0)))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", Mock(return_value=1))
    monkeypatch.setattr(radio_pipeline, "generate_script", write_script)
    monkeypatch.setattr(radio_pipeline, "override_script_title", Mock())
    monkeypatch.setattr(radio_pipeline, "review_script", Mock(return_value={"revised": False, "review_count": 0}))
    monkeypatch.setattr(radio_pipeline, "select_episode_categories", Mock(return_value=[]))
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", Mock(return_value=1))
    monkeypatch.setattr(radio_pipeline, "build_episode", Mock(return_value={"title": "テスト番組", "audio_path": "episode.mp3"}))

    result = radio_pipeline.run_radio_pipeline(
        episode_id, episode_date="2099-01-02", default_episodes_dir=str(tmp_path)
    )
    assert result["title"] == "テスト番組"
    assert success.call_count == 1
    assert EpisodeService().get_episode(episode_id)["status"] == "completed"


def test_orchestrate_success_keeps_completed_when_notification_raises(monkeypatch, tmp_path):
    from app.batch import orchestrate
    from app.services.episode_service import EpisodeService

    monkeypatch.setattr(orchestrate, "EPISODES_DIR", str(tmp_path))
    success = Mock(side_effect=RuntimeError("notification unavailable"))
    monkeypatch.setattr(orchestrate, "notify_success", success)
    monkeypatch.setattr(orchestrate, "import_articles_by_source", Mock(return_value=(1, 0)))
    monkeypatch.setattr(orchestrate, "summarize_articles", Mock(return_value=1))
    def write_script(path, **_kwargs):
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text('{"style":"solo","lines":[{"text":"生成台本"}]}', encoding="utf-8")
        return 1
    monkeypatch.setattr(orchestrate, "generate_script", write_script)
    monkeypatch.setattr(orchestrate, "override_script_title", Mock())
    monkeypatch.setattr(orchestrate, "review_script", Mock(return_value={"revised": False, "review_count": 0}))
    monkeypatch.setattr(orchestrate, "synthesize_episode", Mock(return_value=1))
    monkeypatch.setattr(orchestrate, "build_episode", Mock(return_value={"duration_seconds": 1}))
    monkeypatch.setattr(orchestrate, "_update_episode_audio", Mock())

    orchestrate.run("2099-01-03")
    episode = EpisodeService().get_episode_list()[0]
    assert success.call_count == 1
    assert episode["status"] == "completed"


def test_orchestrate_failure_keeps_failed_when_notification_raises(monkeypatch, tmp_path):
    from app.batch import orchestrate
    from app.services.episode_service import EpisodeService

    monkeypatch.setattr(orchestrate, "EPISODES_DIR", str(tmp_path))
    failure = Mock(side_effect=RuntimeError("notification unavailable"))
    monkeypatch.setattr(orchestrate, "notify_failure", failure)
    monkeypatch.setattr(orchestrate, "import_articles_by_source", Mock(side_effect=RuntimeError("step failed")))

    try:
        orchestrate.run("2099-01-04")
    except RuntimeError as exc:
        assert str(exc) == "step failed"
    else:
        raise AssertionError("orchestrate.run should propagate the generation failure")
    episode = EpisodeService().get_episode_list()[0]
    assert failure.call_count == 1
    assert episode["status"] == "failed"
