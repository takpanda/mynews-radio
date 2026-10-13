import json
import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.services import dgx_busy, thumbnail_service
from app.services.episode_service import EpisodeService


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
    client = _ThumbnailClient([
        _Response({"job_id": "job-123"}),
        _Response({"status": "queued"}),
        _Response({"status": "completed"}),
        _Response(content=b"png-bytes"),
    ])
    monkeypatch.setattr(thumbnail_service.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(thumbnail_service.time, "sleep", lambda _seconds: None)

    path = thumbnail_service.generate_thumbnail(episode_id, episodes_dir=str(tmp_path))

    assert open(path, "rb").read() == b"png-bytes"
    assert EpisodeService().get_episode(episode_id)["thumbnail_path"] == "thumbnail.png"
    assert client.calls[0][2]["json"] == {"title": "Episode title", "topic": "Episode topic"}
    assert [call[0] for call in client.calls] == ["post", "get", "get", "get"]


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


def test_busy_gate_brackets_operation_exception_and_continues_on_http_failure(monkeypatch, caplog):
    endpoints = []

    def busy_call(url, **_kwargs):
        endpoints.append(url.rsplit("/", 1)[-1])
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(dgx_busy, "httpx", SimpleNamespace(post=busy_call), raising=False)
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
        dgx_busy,
        "httpx",
        SimpleNamespace(post=lambda url, **_kwargs: (endpoints.append(url.rsplit("/", 1)[-1]) or _OkResponse())),
        raising=False,
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
