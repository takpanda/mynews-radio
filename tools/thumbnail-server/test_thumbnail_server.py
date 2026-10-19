import asyncio
import importlib.util
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
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


def test_derive_normalizes_invalid_art_direction_values(monkeypatch):
    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda _prompt: (
            '{"scene_prompt":"scene", "headline":"見出し", "visual_style":[], '
            '"tone":null, "accent":["bad", -4, 280], "tag":42, '
            '"kicker":["invalid"], "brand":null}'
        ),
    )

    scene_prompt, spec = thumbnail_server.derive("title", "topic")

    assert scene_prompt == "scene"
    assert spec == {
        "visual_style": "object",
        "tone": "bright-warm",
        "accent": (176, 132, 34),
        "headline": "見出し",
        "tag": "ニュース",
        "kicker": "SPECIAL REPORT",
        "brand": thumbnail_server.DEFAULT_BRAND,
    }


def test_typography_worker_skips_scene_generation(monkeypatch, tmp_path):
    job_id = "typography-job"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None)
    thumbnail_server.jobs[job_id] = job
    spec = {"headline": "見出し", "visual_style": "typography"}
    monkeypatch.setattr(thumbnail_server, "derive", lambda *_args: ("unused", spec))
    monkeypatch.setattr(
        thumbnail_server,
        "gen_scene",
        Mock(side_effect=AssertionError("typography must not generate a scene")),
    )
    compose = Mock(return_value=Image.new("RGB", (960, 540)))
    monkeypatch.setattr(thumbnail_server, "compose", compose)
    monkeypatch.setattr(thumbnail_server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job.transitions == ["queued", "derive", "compose", "done"]
    compose.assert_called_once_with(None, spec, None)
    thumbnail_server.jobs.pop(job_id)


def test_thumbnail_claim_blocks_busy_up_until_thumbnail_releases(monkeypatch):
    job_id = "thumbnail-first"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    derive_started = threading.Event()
    release_derive = threading.Event()
    up_acquired = threading.Event()

    def blocked_derive(*_args):
        derive_started.set()
        assert release_derive.wait(timeout=2)
        return "scene", {"headline": "headline", "visual_style": "object"}

    monkeypatch.setattr(thumbnail_server, "derive", blocked_derive)
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_worker = threading.Thread(target=thumbnail_server.process_job, args=(job_id,))
    thumbnail_worker.start()
    assert derive_started.wait(timeout=1)
    assert thumbnail_server.busy_count() == 1

    def acquire_llm_gate():
        asyncio.run(thumbnail_server.busy_up_ep())
        up_acquired.set()

    llm_worker = threading.Thread(target=acquire_llm_gate)
    llm_worker.start()
    assert not up_acquired.wait(timeout=0.05)
    assert thumbnail_server.busy_count() == 1

    release_derive.set()
    thumbnail_worker.join(timeout=1)
    assert not thumbnail_worker.is_alive()
    assert up_acquired.wait(timeout=1)
    assert thumbnail_server.busy_count() == 1
    thumbnail_server.busy_down()
    llm_worker.join(timeout=1)
    assert not llm_worker.is_alive()
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


def test_busy_claim_keeps_thumbnail_job_queued_until_llm_releases(monkeypatch):
    job_id = "llm-first"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    derive_started = threading.Event()
    monkeypatch.setattr(
        thumbnail_server,
        "derive",
        lambda *_args: (derive_started.set() or (
            "scene", {"headline": "headline", "visual_style": "object"}
        )),
    )
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    asyncio.run(thumbnail_server.busy_up_ep())
    assert thumbnail_server.busy_count() == 1
    thumbnail_worker = threading.Thread(target=thumbnail_server.process_job, args=(job_id,))
    thumbnail_worker.start()
    time.sleep(0.05)
    assert job["status"] == "queued"
    assert not derive_started.is_set()
    assert thumbnail_server.busy_count() == 1

    thumbnail_server.busy_down()
    assert derive_started.wait(timeout=1)
    thumbnail_worker.join(timeout=1)
    assert not thumbnail_worker.is_alive()
    assert job.transitions == ["queued", "derive", "scene", "compose", "done"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


@pytest.mark.asyncio
async def test_busy_up_waiters_do_not_starve_http_thread_pool(monkeypatch):
    waiter_count = 45
    attempted = 0
    real_try_claim_busy = thumbnail_server.try_claim_busy

    def track_try_claim():
        nonlocal attempted
        attempted += 1
        return real_try_claim_busy()

    monkeypatch.setattr(thumbnail_server, "try_claim_busy", track_try_claim)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    transport = httpx.ASGITransport(app=thumbnail_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://thumbnail.test") as client:
        first = await client.post("/busy/up")
        assert first.status_code == 200
        assert first.json() == {"busy": 1}

        waiters = [asyncio.create_task(client.post("/busy/up")) for _ in range(waiter_count)]
        try:
            deadline = asyncio.get_running_loop().time() + 2
            while attempted < waiter_count and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
            assert attempted >= waiter_count

            # This sync endpoint uses Starlette's thread pool. It must remain
            # serviceable while more than the default 40 acquisitions wait.
            released = await asyncio.wait_for(client.post("/busy/down"), timeout=1)
            assert released.status_code == 200

            done, _pending = await asyncio.wait(
                waiters, timeout=1, return_when=asyncio.FIRST_COMPLETED
            )
            assert done, "no waiting /busy/up request acquired the released gate"
            response = done.pop().result()
            assert response.status_code == 200
            assert response.json() == {"busy": 1}
        finally:
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            with thumbnail_server._busy_lock:
                thumbnail_server._busy = 0


class _DrawSpy:
    def __init__(self):
        self.texts = []

    def text(self, position, text, **kwargs):
        self.texts.append((position, text, kwargs))

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def test_compose_draws_headline_inside_left_editorial_column(monkeypatch):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args, **_kwargs: draw)
    spec = {"headline": "物価高の影響", "tag": "経済", "kicker": "ECONOMY", "tone": "bright-warm"}

    image = thumbnail_server.compose(Image.new("RGB", (960, 540)), spec)

    assert image.size == (960, 540)
    headline_calls = [(pos, text, kw["font"]) for pos, text, kw in draw.texts if text in "物価高の影響"]
    assert len(headline_calls) == 2
    for (x, _y), text, font in headline_calls:
        assert x >= 48
        assert x + font.getlength(text) <= 960 * 2 / 3 - 40


@pytest.mark.parametrize("tone", ["bright-warm", "bright-cool", "moody-dark"])
@pytest.mark.parametrize("visual_style", ["person", "object", "symbol", "environment", "typography"])
def test_compose_supports_art_direction_combinations(tone, visual_style):
    scene = None if visual_style == "typography" else Image.new("RGB", (960, 540), (120, 120, 120))
    result = thumbnail_server.compose(scene, {
        "visual_style": visual_style, "tone": tone, "accent": [24, 130, 190],
        "headline": "新しい視点", "tag": "特集", "kicker": "FEATURE", "brand": "わかる解説",
    })

    assert result.size == (960, 540)


def test_compose_long_headline_stays_within_reserved_text_width(monkeypatch):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args, **_kwargs: draw)
    headline = "これは非常に長い見出しで文字領域からはみ出さないことを確認します"
    result = thumbnail_server.compose(Image.new("RGB", (960, 540)), {"headline": headline})

    assert result.size == (960, 540)
    for (x, _y), text, kwargs in draw.texts:
        if text in headline:
            assert x + kwargs["font"].getlength(text) <= 960 * 2 / 3 - 40


def test_compose_fits_every_text_element_inside_editorial_column(monkeypatch):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args, **_kwargs: draw)
    spec = {
        "brand": "毎日のニュースと暮らしに役立つ経済解説ラジオ特別版",
        "kicker": "ECONOMY AND INTERNATIONAL POLITICS SPECIAL REPORT",
        "headline": "見出しを左側の領域に配置する",
        "tag": "国際政治と経済情勢から私たちの暮らしへの影響を読み解く",
    }

    thumbnail_server.compose(Image.new("RGB", (960, 540)), spec)

    right = 960 * 2 / 3 - 40
    assert len(draw.texts) >= 6
    for (x, _y), text, kwargs in draw.texts:
        assert x + kwargs["font"].getlength(text) <= right


@pytest.mark.parametrize(
    ("accent", "expected_text_color"),
    [((255, 255, 255), (20, 22, 24)), ((255, 245, 170), (20, 22, 24)), ((20, 40, 90), (255, 255, 255))],
)
def test_compose_uses_contrasting_tag_text_for_accent(monkeypatch, accent, expected_text_color):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args, **_kwargs: draw)

    thumbnail_server.compose(None, {"accent": accent, "headline": "見出し", "tag": "特集"})

    tag_call = next(call for call in draw.texts if call[1] == "特集")
    assert tag_call[2]["fill"] == expected_text_color
