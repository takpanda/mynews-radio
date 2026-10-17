import importlib.util
import time
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image


SERVER_PATH = Path(__file__).with_name("thumbnail_server.py")
SPEC = importlib.util.spec_from_file_location("thumbnail_server", SERVER_PATH)
thumbnail_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(thumbnail_server)


class _RecordingQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _TrackingJob(dict):
    def __init__(self, **values):
        super().__init__(**values)
        self.transitions = [self["status"]]

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key == "status":
            self.transitions.append(value)


def test_thumbnail_http_enqueue_returns_queued_without_running_derive(monkeypatch):
    queue = _RecordingQueue()
    monkeypatch.setattr(thumbnail_server, "job_q", queue)
    derive = Mock(side_effect=AssertionError("derive must run in the worker"))
    monkeypatch.setattr(thumbnail_server, "derive", derive)
    monkeypatch.setattr(thumbnail_server.uuid, "uuid4", lambda: Mock(hex="job-123"))
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)

    started = time.monotonic()
    with TestClient(thumbnail_server.app) as client:
        response = client.post(
            "/thumbnail", json={"title": "title", "topic": "topic", "brand": "brand"}
        )
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-123", "status": "queued"}
    assert elapsed < 2
    assert queue.items == ["job-123"]
    assert thumbnail_server.jobs["job-123"]["status"] == "queued"
    assert thumbnail_server.jobs["job-123"]["title"] == "title"
    derive.assert_not_called()
    thumbnail_server.jobs.pop("job-123")


def test_worker_marks_ollama_failure_failed_and_releases_busy(monkeypatch):
    job_id = "ollama-failure"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        Mock(side_effect=RuntimeError("Ollama timed out")),
    )
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "failed"
    assert job["error"] == "Ollama timed out"
    assert job.transitions == ["queued", "derive", "failed"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


def test_worker_completes_after_successful_derive(monkeypatch, tmp_path):
    job_id = "successful-job"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda _prompt: '{"scene_prompt":"scene", "headline":"headline", "highlight":"head"}',
    )
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
    monkeypatch.setattr(thumbnail_server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job.transitions == ["queued", "derive", "scene", "compose", "done"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


class _Font:
    def __init__(self, size):
        self.size = size

    def getlength(self, text):
        return len(text) * 10

    def getbbox(self, text):
        return (0, 0, self.getlength(text), 20)


class _DrawSpy:
    def __init__(self):
        self.texts = []
        self.banners = []

    def text(self, position, text, **kwargs):
        self.texts.append((position, text, kwargs))

    def rounded_rectangle(self, bounds, **kwargs):
        self.banners.append((bounds, kwargs))

    def textbbox(self, position, text, font, stroke_width=0):
        x, y = position
        return (
            x - stroke_width,
            y - stroke_width,
            x + font.getlength(text) + stroke_width,
            y + font.getbbox(text)[3] + stroke_width,
        )


def _compose(monkeypatch, headline, highlight):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server, "F", lambda _path, size, **_kwargs: _Font(size))
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args: draw)

    image = thumbnail_server.compose(Image.new("RGB", (960, 540)), headline, highlight)
    return image, draw


def _headline_texts(draw):
    texts = [text for _position, text, _kwargs in draw.texts if text != thumbnail_server.DEFAULT_BRAND]
    return list(dict.fromkeys(texts))


def test_compose_draws_highlight_at_start_when_top_line_is_empty(monkeypatch):
    image, draw = _compose(monkeypatch, "円安ショック！食費が激増", "円安")

    assert image.size == (960, 540)
    assert _headline_texts(draw) == ["円安ショック！食費が激増"]
    assert len(draw.banners) == 1


def test_compose_keeps_two_lines_for_middle_and_trailing_highlights(monkeypatch):
    for headline, highlight, expected_lines in (
        ("物価高の影響", "高", ["物価", "高の影響"]),
        ("物価への影響", "響", ["物価への影", "響"]),
    ):
        _image, draw = _compose(monkeypatch, headline, highlight)

        assert _headline_texts(draw) == expected_lines
        assert len(draw.banners) == 1


def test_compose_centers_single_line_without_highlight(monkeypatch):
    _image, draw = _compose(monkeypatch, "音声合成が使える", "")

    headline_calls = [call for call in draw.texts if call[1] != thumbnail_server.DEFAULT_BRAND]
    assert _headline_texts(draw) == ["音声合成が使える"]
    assert headline_calls[1][0][1] == (540 - 20) // 2
    assert draw.banners == []
