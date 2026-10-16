import json
import logging
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import dgx_busy, thumbnail_service
from app.services.episode_service import EpisodeService
from app.db.connection import get_db_connection


class _Response:
    def __init__(self, data=None, content=b"", error=None):
        self._data = data or {}
        self.content = content
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._data


class _ThumbnailClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return next(self.responses)

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return next(self.responses)


def _episode(tmp_path, title="Episode title", topic="Episode topic"):
    episode_id = EpisodeService().create_episode("2099-11-12", status="completed")
    episode_dir = tmp_path / str(episode_id)
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"title": title, "subtitle": topic}), encoding="utf-8"
    )
    return episode_id


def test_generate_thumbnail_saves_image_and_updates_path(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET program_snapshot = ? WHERE id = ?",
            (json.dumps({"name": "ニュースのとなり"}), episode_id),
        )
    client = _ThumbnailClient([
        _Response({"job_id": "job-123"}),
        _Response({"status": "queued"}),
        _Response({"status": "completed"}),
        _Response(content=b"png-bytes"),
    ])
    client_options = []
    monkeypatch.setattr(
        thumbnail_service.httpx,
        "Client",
        lambda **kwargs: (client_options.append(kwargs) or client),
    )
    monkeypatch.setattr(
        thumbnail_service,
        "get_settings",
        lambda: SimpleNamespace(
            thumbnail_service_url="http://thumbnail.invalid",
            thumbnail_http_timeout=10.0,
            thumbnail_enqueue_timeout=120.0,
            thumbnail_poll_interval=5.0,
            thumbnail_job_timeout=900.0,
        ),
    )
    monkeypatch.setattr(
        thumbnail_service,
        "time",
        SimpleNamespace(
            monotonic=Mock(side_effect=[0.0, 11.0, 11.0, 11.0]),
            sleep=lambda _seconds: None,
        ),
    )

    path = thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))

    assert open(path, "rb").read() == b"png-bytes"
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] == "thumbnail.png"
    assert client.calls[0][2]["json"] == {
        "title": "Episode title",
        "topic": "Episode topic",
        "brand": "ニュースのとなり",
    }
    assert client_options == [{"timeout": 10.0}]
    assert client.calls[0][2]["timeout"] == 120.0
    assert all("timeout" not in call[2] for call in client.calls[1:])
    assert [call[0] for call in client.calls] == ["post", "get", "get", "get"]


def test_resolve_brand_uses_program_name_when_snapshot_is_missing():
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO programs (id, name, kind, definition) VALUES (?, ?, ?, ?)",
            ("tech-news", "テックニュース", "radio", "{}"),
        )

    assert thumbnail_service._resolve_brand(
        {"program_snapshot": None, "program_id": "tech-news"}
    ) == "テックニュース"


def test_resolve_brand_returns_none_for_legacy_episode():
    assert thumbnail_service._resolve_brand(
        {"program_snapshot": None, "program_id": None}
    ) is None


def test_enqueue_timeout_does_not_poll_or_persist_thumbnail(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)

    client = _ThumbnailClient([])

    def enqueue_timed_out(url, **kwargs):
        client.calls.append(("post", url, kwargs))
        raise httpx.TimeoutException("enqueue timed out")

    client.post = enqueue_timed_out
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        thumbnail_service,
        "get_settings",
        lambda: SimpleNamespace(
            thumbnail_service_url="http://thumbnail.invalid",
            thumbnail_http_timeout=10.0,
            thumbnail_enqueue_timeout=120.0,
            thumbnail_poll_interval=5.0,
            thumbnail_job_timeout=900.0,
        ),
    )

    with pytest.raises(httpx.TimeoutException, match="enqueue timed out"):
        thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))

    assert len(client.calls) == 1
    assert client.calls[0][2]["timeout"] == 120.0
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] is None
    assert not (tmp_path / str(episode_id) / "thumbnail.png").exists()


def test_service_stop_does_not_change_thumbnail_path(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)

    def stopped(**_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(thumbnail_service.httpx, "Client", stopped)
    with pytest.raises(httpx.ConnectError):
        thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] is None
    assert not (tmp_path / str(episode_id) / "thumbnail.png").exists()


def test_failed_job_does_not_persist_thumbnail(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)
    client = _ThumbnailClient([_Response({"job_id": "job-123"}), _Response({"status": "failed"})])
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(RuntimeError, match="job failed"):
        thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] is None


def test_poll_timeout_does_not_retry_or_persist(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)
    client = _ThumbnailClient([_Response({"job_id": "job-123"}), _Response({"status": "queued"})])
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        thumbnail_service,
        "time",
        SimpleNamespace(monotonic=Mock(side_effect=[0.0, 0.1, 0.1, 2.0]), sleep=lambda _seconds: None),
    )
    monkeypatch.setenv("THUMBNAIL_JOB_TIMEOUT", "1")
    from app.config import get_settings
    get_settings.cache_clear()

    try:
        with pytest.raises(TimeoutError):
            thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))
    finally:
        get_settings.cache_clear()
    assert len(client.calls) == 2
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] is None


def test_existing_thumbnail_requires_explicit_overwrite(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)
    output = tmp_path / str(episode_id) / "thumbnail.png"
    output.write_bytes(b"previous")
    EpisodeService().update_episode_thumbnail_path(episode_id, "thumbnail.png")

    with pytest.raises(FileExistsError):
        thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))
    assert output.read_bytes() == b"previous"


def test_overwrite_failure_preserves_existing_image_and_path(tmp_path, monkeypatch):
    episode_id = _episode(tmp_path)
    output = tmp_path / str(episode_id) / "thumbnail.png"
    output.write_bytes(b"previous")
    EpisodeService().update_episode_thumbnail_path(episode_id, "thumbnail.png")
    client = _ThumbnailClient([
        _Response({"job_id": "job-123"}),
        _Response({"status": "failed"}),
    ])
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(RuntimeError, match="job failed"):
        thumbnail_service.generate_thumbnail(
            episode_id, episodes_dir=str(tmp_path), overwrite=True
        )

    episode = EpisodeService().get_episode(episode_id)
    assert episode["thumbnail_path"] == "thumbnail.png"
    assert output.read_bytes() == b"previous"


def test_busy_gate_brackets_operation_exception_and_continues_on_http_failure(monkeypatch, caplog):
    endpoints = []

    def busy_call(url, **_kwargs):
        endpoints.append(url.rsplit("/", 1)[-1])
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(dgx_busy.httpx, "post", busy_call)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="phase failed"):
            dgx_busy.run_with_dgx_busy("script", lambda: (_ for _ in ()).throw(ValueError("phase failed")))

    assert endpoints == ["up", "down"]
    assert "busy/up request failed" in caplog.text
    assert "busy/down request failed" in caplog.text
    assert "offline" not in caplog.text


def test_busy_gate_returns_operation_result_and_brackets_success(monkeypatch):
    endpoints = []

    class _OkResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        dgx_busy.httpx,
        "post",
        lambda url, **_kwargs: (endpoints.append(url.rsplit("/", 1)[-1]) or _OkResponse()),
    )
    assert dgx_busy.run_with_dgx_busy("tts", lambda: 42) == 42
    assert endpoints == ["up", "down"]


def test_async_thumbnail_start_does_not_wait_for_worker(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    workers = []

    def blocked(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        return "/unused"

    real_thread = threading.Thread

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        workers.append(thread)
        return thread

    monkeypatch.setattr(thumbnail_service, "generate_thumbnail", blocked)
    monkeypatch.setattr(threading, "Thread", capture_thread)
    thumbnail_service.start_thumbnail_generation(10, title="title", topic="topic")

    assert entered.wait(timeout=1)
    assert workers[0].is_alive()
    release.set()
    workers[0].join(timeout=1)
    assert not workers[0].is_alive()


def _run_successful_pipeline_with_thumbnail(
    episode_id, tmp_path, monkeypatch, notify_success
):
    from app.batch import radio_pipeline

    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _source: (1, 0))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", lambda *_args, **_kwargs: 1)

    def write_script(path, **_kwargs):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"title": "Pipeline title", "subtitle": "Pipeline topic", "lines": [{"text": "line"}]},
                f,
            )
        return 1

    monkeypatch.setattr(radio_pipeline, "generate_script", write_script)
    monkeypatch.setattr(
        radio_pipeline,
        "review_script",
        lambda *_args, **_kwargs: {"revised": False, "review_count": 0},
    )
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        radio_pipeline,
        "build_episode",
        lambda *_args, **_kwargs: {"audio_path": "episode.mp3", "title": "Pipeline title"},
    )
    monkeypatch.setattr(radio_pipeline, "notify_success", notify_success)
    return radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-11-12",
        default_episodes_dir=str(tmp_path),
        tts_base_url="http://tts.invalid",
        tts_speaker_male=1,
        tts_speaker_female=2,
    )


def test_pipeline_completes_and_notifies_while_thumbnail_worker_is_blocked(tmp_path, monkeypatch):
    episode_id, _ = EpisodeService().create_radio_episode("2099-11-12")
    started = threading.Event()
    release = threading.Event()
    notify = Mock()

    def blocked_worker(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)
        return "unused.png"

    monkeypatch.setattr(thumbnail_service, "generate_thumbnail", blocked_worker)

    try:
        result = _run_successful_pipeline_with_thumbnail(
            episode_id, tmp_path, monkeypatch, notify
        )
        assert result is not None
        assert started.wait(timeout=1)
        assert not release.is_set()
        notify.assert_called_once()
        assert EpisodeService().get_episode(episode_id)["status"] == "completed"
    finally:
        release.set()


def test_pipeline_completion_and_notification_survive_thumbnail_failure(tmp_path, monkeypatch):
    episode_id, _ = EpisodeService().create_radio_episode("2099-11-12")
    attempted = threading.Event()
    notify = Mock()

    def failed_worker(*_args, **_kwargs):
        attempted.set()
        raise RuntimeError("thumbnail failed")

    monkeypatch.setattr(thumbnail_service, "generate_thumbnail", failed_worker)
    result = _run_successful_pipeline_with_thumbnail(
        episode_id, tmp_path, monkeypatch, notify
    )

    assert result is not None
    assert attempted.wait(timeout=1)
    notify.assert_called_once()
    assert EpisodeService().get_episode(episode_id)["status"] == "completed"
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] is None


def test_manual_cli_updates_only_requested_episode_without_regeneration_or_notification(
    tmp_path, monkeypatch
):
    from scripts import regenerate_thumbnail

    monkeypatch.setenv("EPISODES_DIR", str(tmp_path))
    target_id = _episode(tmp_path, title="Target", topic="Target topic")
    other_id = _episode(tmp_path, title="Other", topic="Other topic")
    target_script = (tmp_path / str(target_id) / "script.json").read_bytes()
    other_script = (tmp_path / str(other_id) / "script.json").read_bytes()
    client = _ThumbnailClient([
        _Response({"job_id": "target-job"}),
        _Response({"status": "completed"}),
        _Response(content=b"target-png"),
    ])
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(sys, "argv", ["regenerate_thumbnail.py", str(target_id)])

    with patch.object(EpisodeService, "complete_radio_episode_with_notification") as complete, \
         patch("app.batch.radio_pipeline.run_radio_pipeline") as run_pipeline, \
         patch("app.api.generate.notify_success") as notify:
        assert regenerate_thumbnail.main() == 0

    target = EpisodeService().get_episode(target_id)
    other = EpisodeService().get_episode(other_id)
    assert (tmp_path / str(target_id) / "thumbnail.png").read_bytes() == b"target-png"
    assert target["thumbnail_path"] == "thumbnail.png"
    assert target["status"] == "completed"
    assert other["thumbnail_path"] is None
    assert other["status"] == "completed"
    assert (tmp_path / str(target_id) / "script.json").read_bytes() == target_script
    assert (tmp_path / str(other_id) / "script.json").read_bytes() == other_script
    assert [call[0] for call in client.calls].count("post") == 1
    complete.assert_not_called()
    run_pipeline.assert_not_called()
    notify.assert_not_called()
