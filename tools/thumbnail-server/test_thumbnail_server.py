import asyncio
import importlib.util
import json
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


def test_worker_falls_back_after_ollama_failure_and_releases_busy(monkeypatch):
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
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
    monkeypatch.setattr(thumbnail_server, "touch_activity", lambda: None)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job["art_direction"]["visual_style"] == "person"
    assert job.transitions == ["queued", "derive", "scene", "compose", "done"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


def test_derive_validates_schema_and_builds_style_specific_prompts(monkeypatch):
    monkeypatch.setattr(thumbnail_server, "_ollama_chat", lambda _prompt: "not json")
    cases = [
        ({"title": "朝のAIニュース", "subtitle": "AIの安全性"}, "symbol", "bright-cool"),
        ({"title": "都市の防災", "subtitle": "街の災害対策"}, "environment", "moody-dark"),
        ({"title": "今週のまとめ", "subtitle": "ニュース総集編"}, "typography", "bright-warm"),
    ]

    for episode, expected_style, expected_tone in cases:
        direction = thumbnail_server.derive(**episode)
        assert direction["visual_style"] == expected_style
        assert direction["tone"] == expected_tone
        assert direction["accent"] == list(thumbnail_server.ACCENTS[expected_tone])
        assert direction["headline"]
        assert direction["tag"]
        assert "right third" in direction["scene_prompt"]
        assert "left two thirds" in direction["scene_prompt"]


def test_derive_accepts_valid_schema_for_all_five_styles(monkeypatch):
    responses = [
        ("person", "bright-warm", "Japanese"),
        ("object", "bright-cool", "editorial still life"),
        ("symbol", "bright-cool", "abstract luminous symbol"),
        ("environment", "moody-dark", "Japanese city"),
        ("typography", "bright-warm", "abstract editorial background"),
    ]
    for index, (style, tone, prompt_fragment) in enumerate(responses):
        expected = {
            "visual_style": style,
            "tone": tone,
            "accent": [1, 2, 3],
            "headline": f"有効見出し{index}",
            "tag": f"タグ{index}",
            "kicker": "FEATURE",
            "brand": "番組名",
        }
        monkeypatch.setattr(
            thumbnail_server,
            "_ollama_chat",
            lambda _prompt, payload=expected: json.dumps(payload, ensure_ascii=False),
        )

        direction = thumbnail_server.derive(episode_id="episode-1", title="都市の未来")

        assert direction["visual_style"] == style
        assert direction["tone"] == tone
        assert direction["accent"] == list(thumbnail_server.ACCENTS[tone])
        assert direction["headline"] == expected["headline"]
        assert direction["tag"] == expected["tag"]
        assert direction["kicker"] == expected["kicker"]
        assert direction["brand"] == expected["brand"]
        assert prompt_fragment in direction["scene_prompt"]


def test_derive_string_episode_id_preserves_title_and_605_direction(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda prompt: (prompts.append(prompt) or "{}"),
    )

    direction = thumbnail_server.derive(episode_id="605", title="都市の未来", subtitle="都市計画")

    assert "episode_id: 605" in prompts[0]
    assert "title: 都市の未来" in prompts[0]
    assert "subtitle: 都市計画" in prompts[0]
    assert direction["visual_style"] == "person"
    assert direction["tone"] == "bright-warm"
    assert direction["headline"] == "AIが進めば、信頼は、どこへ。"


def test_derive_rejects_invalid_schema_values_and_bounds_headline(monkeypatch):
    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda _prompt: json.dumps({
            "visual_style": "object", "tone": "bright-warm", "headline": ["見出し"],
            "tag": [], "kicker": None, "brand": 42,
        }, ensure_ascii=False),
    )
    invalid_field_types = thumbnail_server.derive(title="製品ニュース")
    assert invalid_field_types["visual_style"] == "object"
    assert invalid_field_types["headline"] == "製品ニュース"
    assert invalid_field_types["tag"] == "製品ニュース"
    assert invalid_field_types["kicker"] == "SPECIAL REPORT"
    assert invalid_field_types["brand"] == thumbnail_server.DEFAULT_BRAND

    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda _prompt: json.dumps({
            "visual_style": "object", "tone": "ultraviolet", "headline": "長い見出し" * 10,
        }, ensure_ascii=False),
    )
    invalid_enum = thumbnail_server.derive(title="都市の未来")
    assert invalid_enum["visual_style"] == "environment"

    monkeypatch.setattr(
        thumbnail_server,
        "_ollama_chat",
        lambda _prompt: json.dumps({
            "visual_style": "object", "tone": "bright-cool", "headline": "長い見出し" * 10,
            "tag": "スマートフォン", "kicker": "FEATURE", "brand": "番組名",
        }, ensure_ascii=False),
    )
    bounded = thumbnail_server.derive(title="製品ニュース")
    assert len(bounded["headline"]) == thumbnail_server.MAX_HEADLINE_CHARS
    assert bounded["visual_style"] == "object"


def test_derive_person_prompt_requires_japanese_and_keeps_face_clear(monkeypatch):
    monkeypatch.setattr(thumbnail_server, "_ollama_chat", lambda _prompt: "{}")
    direction = thumbnail_server.derive(title="暮らしの話題")

    assert direction["visual_style"] == "person"
    assert "Japanese" in direction["scene_prompt"]
    assert "face unobstructed" in direction["scene_prompt"]
    assert "do not overlay symbols, keys, or graphics on the face" in direction["scene_prompt"]


def test_derive_605_uses_reference_direction(monkeypatch):
    monkeypatch.setattr(thumbnail_server, "_ollama_chat", lambda _prompt: "bad response")
    direction = thumbnail_server.derive(episode_id=605, title="AIと信頼")

    assert direction["visual_style"] == "person"
    assert direction["tone"] == "bright-warm"
    assert direction["accent"] == [196, 166, 96]
    assert direction["headline"] == "AIが進めば、信頼は、どこへ。"
    assert direction["tag"] == "AI × 信頼"


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


def test_thumbnail_claim_blocks_busy_up_until_thumbnail_releases(monkeypatch):
    job_id = "thumbnail-first"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    derive_started = threading.Event()
    release_derive = threading.Event()
    up_acquired = threading.Event()

    def blocked_derive(*_args, **_kwargs):
        derive_started.set()
        assert release_derive.wait(timeout=2)
        return "scene", "headline", "", ""

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
        lambda *_args, **_kwargs: (derive_started.set() or ("scene", "headline", "", "")),
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
