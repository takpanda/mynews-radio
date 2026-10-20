import asyncio
import importlib.util
import io
import json
import threading
import time
import uuid
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
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job["art_direction"]["visual_style"] == "person"
    assert job.transitions == ["queued", "derive", "scene", "compose", "done"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


def test_gen_scene_submits_qwen_workflow_and_downloads_saved_image(monkeypatch, tmp_path):
    workflow_path = tmp_path / "workflow.json"
    source = json.loads((SERVER_PATH.parent / "workflows" / "qwen_image_2_1_turbo_t2i.json").read_text())
    workflow_path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(thumbnail_server, "COMFYUI_WORKFLOW_PATH", workflow_path)
    image_buffer = io.BytesIO()
    Image.new("RGB", (1280, 720), (12, 34, 56)).save(image_buffer, format="PNG")

    class _Response:
        def __init__(self, data=None, content=b""):
            self.data = data
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    class _Client:
        def __init__(self, **_kwargs):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            self.calls.append(("post", url, kwargs))
            return _Response({"prompt_id": "comfy-job"})

        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            if url.endswith("/history/comfy-job"):
                return _Response({"comfy-job": {
                    "status": {"status_str": "success"},
                    "outputs": {"462": {"images": [{
                        "filename": "thumb_mag_00001.png", "subfolder": "", "type": "output",
                    }]}},
                }})
            return _Response(content=image_buffer.getvalue())

    clients = []

    def make_client(**kwargs):
        client = _Client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(thumbnail_server.httpx, "Client", make_client)

    result = thumbnail_server.gen_scene("editorial scene prompt")

    calls = clients[0].calls
    submitted = calls[0][2]["json"]["prompt"]
    assert uuid.UUID(calls[0][2]["json"]["prompt_id"])
    assert submitted["452"]["inputs"]["prompt"] == "editorial scene prompt"
    assert submitted["452"]["inputs"]["resolution"] == 1024
    assert submitted["456"]["inputs"]["width"] == 1280
    assert submitted["456"]["inputs"]["height"] == 720
    assert submitted["488"]["inputs"]["noise_seed"] != source["488"]["inputs"]["noise_seed"]
    assert calls[1][1].endswith("/history/comfy-job")
    assert calls[2][1].endswith("/view")
    assert calls[2][2]["params"] == {
        "filename": "thumb_mag_00001.png", "subfolder": "", "type": "output",
    }
    assert result.size == (960, 540)
    assert result.getpixel((10, 10)) == (12, 34, 56)
    assert json.loads(workflow_path.read_text())["452"]["inputs"]["prompt"] == ""


def test_comfyui_failure_marks_job_failed_and_releases_busy(monkeypatch):
    job_id = "comfy-failure"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(thumbnail_server, "derive", lambda **_kwargs: {
        "scene_prompt": "scene", "headline": "headline", "tag": "tag",
        "visual_style": "person", "tone": "bright-warm", "accent": [196, 166, 96],
        "kicker": "FEATURE", "brand": thumbnail_server.DEFAULT_BRAND,
    })
    monkeypatch.setattr(
        thumbnail_server, "gen_scene", Mock(side_effect=RuntimeError("ComfyUI is unavailable"))
    )
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "failed"
    assert job["error"] == "ComfyUI is unavailable"
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)


@pytest.mark.parametrize("failure_mode", ["job_timeout", "history_timeout"])
def test_comfyui_timeout_cancels_active_job_before_releasing_busy(
    monkeypatch, tmp_path, failure_mode
):
    job_id = f"comfy-{failure_mode}"
    prompt_id = "12345678-1234-5678-1234-567812345678"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(thumbnail_server, "COMFYUI_STATE_PATH", tmp_path / "active.json")
    monkeypatch.setattr(thumbnail_server.uuid, "uuid4", lambda: uuid.UUID(prompt_id))
    monkeypatch.setattr(thumbnail_server, "COMFYUI_JOB_TIMEOUT", 0 if failure_mode == "job_timeout" else 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_CLEANUP_TIMEOUT", 1)
    monkeypatch.setattr(thumbnail_server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(thumbnail_server, "derive", lambda **_kwargs: {
        "scene_prompt": "scene", "headline": "headline", "tag": "tag",
        "visual_style": "person", "tone": "bright-warm", "accent": [196, 166, 96],
        "kicker": "FEATURE", "brand": thumbnail_server.DEFAULT_BRAND,
    })
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0
    remote_active = {"value": True}
    client_index = {"value": 0}

    class _Response:
        def __init__(self, data=None):
            self.data = data or {}
            self.content = b""
        def raise_for_status(self):
            return None
        def json(self):
            return self.data

    class _Client:
        def __init__(self, **_kwargs):
            self.index = client_index["value"]
            client_index["value"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def post(self, url, **kwargs):
            if url.endswith("/prompt"):
                return _Response({"prompt_id": prompt_id})
            assert url.endswith("/interrupt")
            assert kwargs["json"] == {"prompt_id": prompt_id}
            remote_active["value"] = False
            return _Response()
        def get(self, url, **_kwargs):
            if url.endswith(f"/history/{prompt_id}"):
                if self.index == 0 and failure_mode == "history_timeout":
                    raise httpx.ReadTimeout("history request timed out")
                if not remote_active["value"]:
                    return _Response({prompt_id: {"status": {"status_str": "error"}}})
                return _Response()
            assert url.endswith("/queue")
            running = [[1, prompt_id]] if remote_active["value"] else []
            return _Response({"queue_running": running, "queue_pending": []})

    monkeypatch.setattr(thumbnail_server.httpx, "Client", _Client)

    thumbnail_server.process_job(job_id)

    assert job["status"] == "failed"
    assert remote_active["value"] is False
    assert thumbnail_server.busy_count() == 0
    assert thumbnail_server.try_claim_busy() is True
    thumbnail_server.busy_down()
    thumbnail_server.jobs.pop(job_id)


def test_comfyui_recovery_keeps_busy_claimed_until_connection_returns(monkeypatch, tmp_path):
    job_id = "comfy-disconnected"
    prompt_id = "12345678-1234-5678-1234-567812345678"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(thumbnail_server, "COMFYUI_STATE_PATH", tmp_path / "active.json")
    monkeypatch.setattr(thumbnail_server.uuid, "uuid4", lambda: uuid.UUID(prompt_id))
    monkeypatch.setattr(thumbnail_server, "COMFYUI_CLEANUP_TIMEOUT", 1)
    monkeypatch.setattr(thumbnail_server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(thumbnail_server, "derive", lambda **_kwargs: {
        "scene_prompt": "scene", "headline": "headline", "tag": "tag",
        "visual_style": "person", "tone": "bright-warm", "accent": [196, 166, 96],
        "kicker": "FEATURE", "brand": thumbnail_server.DEFAULT_BRAND,
    })
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0
    recovery_states = []
    monkeypatch.setattr(
        thumbnail_server, "_start_comfyui_recovery", lambda state: recovery_states.append(state)
    )
    remote_active = {"value": True}
    client_index = {"value": 0}

    class _Response:
        def __init__(self, data=None):
            self.data = data or {}
            self.content = b""
        def raise_for_status(self):
            return None
        def json(self):
            return self.data

    class _Client:
        def __init__(self, **_kwargs):
            self.index = client_index["value"]
            client_index["value"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def post(self, url, **kwargs):
            if url.endswith("/prompt"):
                return _Response({"prompt_id": prompt_id})
            assert url.endswith("/interrupt")
            assert kwargs["json"] == {"prompt_id": prompt_id}
            remote_active["value"] = False
            return _Response()
        def get(self, url, **_kwargs):
            if self.index == 0 and url.endswith(f"/history/{prompt_id}"):
                raise httpx.ReadTimeout("history is disconnected")
            if self.index == 1:
                raise httpx.ConnectError("ComfyUI is unreachable")
            if url.endswith(f"/history/{prompt_id}"):
                if not remote_active["value"]:
                    return _Response({prompt_id: {"status": {"status_str": "error"}}})
                return _Response()
            running = [[1, prompt_id]] if remote_active["value"] else []
            return _Response({"queue_running": running, "queue_pending": []})

    monkeypatch.setattr(thumbnail_server.httpx, "Client", _Client)

    thumbnail_server.process_job(job_id)

    assert job["status"] == "failed"
    assert remote_active["value"] is True
    assert thumbnail_server.busy_count() == 1
    assert thumbnail_server.try_claim_busy() is False
    assert recovery_states == [{"prompt_id": prompt_id, "submitted": True}]

    client_index["value"] = 2
    thumbnail_server._recover_comfyui_state(recovery_states[0])

    assert remote_active["value"] is False
    assert thumbnail_server.busy_count() == 0
    assert thumbnail_server.try_claim_busy() is True
    thumbnail_server.busy_down()
    thumbnail_server.jobs.pop(job_id)


def test_comfyui_lost_prompt_response_recovers_with_default_quiet_period(
    monkeypatch, tmp_path
):
    job_id = "comfy-lost-prompt-response"
    state_path = tmp_path / "active.json"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None,
                       highlight=None)
    thumbnail_server.jobs[job_id] = job
    monkeypatch.setattr(thumbnail_server, "COMFYUI_STATE_PATH", state_path)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_CLEANUP_TIMEOUT", 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_UNKNOWN_QUIET_PERIOD", 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_REQUEST_TIMEOUT", 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_JOB_TIMEOUT", 900)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_POLL_INTERVAL", 2)
    monkeypatch.setattr(thumbnail_server, "derive", lambda **_kwargs: {
        "scene_prompt": "scene", "headline": "headline", "tag": "tag",
        "visual_style": "person", "tone": "bright-warm", "accent": [196, 166, 96],
        "kicker": "FEATURE", "brand": thumbnail_server.DEFAULT_BRAND,
    })
    clock = {"now": 0.0, "queue_reads": 0}
    monkeypatch.setattr(thumbnail_server.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(thumbnail_server.time, "sleep", lambda seconds: clock.__setitem__(
        "now", clock["now"] + seconds
    ))
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    class _Response:
        def __init__(self, data=None):
            self.data = data or {}
        def raise_for_status(self):
            return None
        def json(self):
            return self.data

    class _Client:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def post(self, url, **_kwargs):
            assert url.endswith("/prompt")
            # The remote accepted the prompt, but the response was lost.
            clock["now"] += 0.1
            raise httpx.ReadTimeout("prompt response was lost")
        def get(self, url, **_kwargs):
            assert url.endswith("/queue")
            clock["queue_reads"] += 1
            clock["now"] += 0.1 if clock["queue_reads"] == 1 else 0.001
            # The first two snapshots show the unknown job; it then completes.
            running = [[1, "unknown-remote-job"]] if clock["queue_reads"] <= 2 else []
            return _Response({"queue_running": running, "queue_pending": []})

    monkeypatch.setattr(thumbnail_server.httpx, "Client", _Client)

    thumbnail_server.process_job(job_id)

    assert job["status"] == "failed"
    assert "timed out" in job["error"]
    assert clock["queue_reads"] > 30
    assert clock["now"] >= 30
    assert not state_path.exists()
    assert thumbnail_server.busy_count() == 0
    assert thumbnail_server.try_claim_busy() is True
    thumbnail_server.busy_down()
    thumbnail_server.jobs.pop(job_id)


def test_comfyui_restart_recovers_marker_with_default_quiet_period_and_delayed_http(
    monkeypatch, tmp_path
):
    state_path = tmp_path / "active.json"
    state_path.write_text(json.dumps({"prompt_id": "unknown", "submitted": False}))
    monkeypatch.setattr(thumbnail_server, "COMFYUI_STATE_PATH", state_path)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_CLEANUP_TIMEOUT", 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_UNKNOWN_QUIET_PERIOD", 30)
    monkeypatch.setattr(thumbnail_server, "COMFYUI_REQUEST_TIMEOUT", 30)
    clock = {"now": 0.0, "queue_reads": 0}
    monkeypatch.setattr(thumbnail_server.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(thumbnail_server.time, "sleep", lambda seconds: clock.__setitem__(
        "now", clock["now"] + seconds
    ))
    recovery_states = []
    monkeypatch.setattr(
        thumbnail_server, "_start_comfyui_recovery", lambda state: recovery_states.append(state)
    )
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 1

    class _Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"queue_running": [], "queue_pending": []}

    class _Client:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def get(self, url, **_kwargs):
            assert url.endswith("/queue")
            clock["queue_reads"] += 1
            clock["now"] += 0.1 if clock["queue_reads"] == 1 else 0.001
            return _Response()

    monkeypatch.setattr(thumbnail_server.httpx, "Client", _Client)

    thumbnail_server._resume_comfyui_recovery()
    assert recovery_states == [{"prompt_id": "unknown", "submitted": False}]
    thumbnail_server._recover_comfyui_state(recovery_states[0])

    assert clock["now"] >= 30
    assert clock["queue_reads"] > 30
    assert not state_path.exists()
    assert thumbnail_server.busy_count() == 0
    assert thumbnail_server.try_claim_busy() is True
    thumbnail_server.busy_down()


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
    assert "entire head and face fully inside the rightmost third" in direction["scene_prompt"]
    assert "no part of the face may touch or cross that boundary" in direction["scene_prompt"]
    assert direction["preserve_scene_right"] is True


def test_compose_episode_605_moves_panel_boundary_without_cropping_scene():
    scene = Image.new("RGB", (960, 540), (20, 40, 80))
    scene.paste((220, 30, 40), (600, 100, 650, 400))

    result = thumbnail_server.compose(scene, {
        "tone": "bright-warm", "preserve_scene_right": True,
    })

    assert result.getpixel((625, 200)) == (220, 30, 40)
    assert result.getpixel((350, 20)) == (246, 239, 222)
    assert result.getpixel((380, 20)) == (20, 40, 80)
    assert sum(1 for color in result.get_flattened_data() if color == (220, 30, 40)) == 15_000
    assert sum(1 for color in result.get_flattened_data() if color == (220, 30, 40)) == 15_000


def test_compose_keeps_episode_605_subject_with_background_vertical_line():
    scene = Image.new("RGB", (960, 540), (100, 100, 100))
    scene.paste((160, 160, 160), (600, 0, 605, 540))
    scene.paste((220, 30, 40), (720, 100, 880, 400))

    result = thumbnail_server.compose(scene, {
        "tone": "bright-warm", "preserve_scene_right": True,
    })

    assert result.getpixel((602, 50)) == (160, 160, 160)
    assert result.getpixel((800, 200)) == (220, 30, 40)
    colors = {color: count for count, color in result.getcolors(maxcolors=960 * 540)}
    assert colors[(220, 30, 40)] == 48_000


def test_compose_keeps_episode_605_subject_on_right_over_vertical_gradient():
    scene = Image.new("RGB", (960, 540))
    draw = thumbnail_server.ImageDraw.Draw(scene)
    for y in range(540):
        shade = round(100 + 60 * y / 539)
        draw.line((0, y, 959, y), fill=(shade, shade, shade))
    scene.paste((220, 30, 40), (720, 100, 880, 400))

    result = thumbnail_server.compose(scene, {
        "tone": "bright-warm", "preserve_scene_right": True,
    })

    assert result.getpixel((800, 200)) == (220, 30, 40)
    colors = {color: count for count, color in result.getcolors(maxcolors=960 * 540)}
    assert colors[(220, 30, 40)] == 48_000


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
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job.transitions == ["queued", "derive", "scene", "compose", "done"]
    assert thumbnail_server.busy_count() == 0
    thumbnail_server.jobs.pop(job_id)



def test_typography_worker_skips_scene_generation(monkeypatch, tmp_path):
    job_id = "typography-job"
    job = _TrackingJob(status="queued", title="title", topic="topic", brand=None,
                       path=None, error=None, scene_prompt=None, headline=None)
    thumbnail_server.jobs[job_id] = job
    direction = {
        "visual_style": "typography", "tone": "bright-warm", "accent": [196, 166, 96],
        "headline": "見出し", "tag": "特集", "kicker": "FEATURE",
        "brand": thumbnail_server.DEFAULT_BRAND, "scene_prompt": "unused",
    }
    monkeypatch.setattr(thumbnail_server, "derive", lambda **_kwargs: direction)
    gen_scene = Mock(side_effect=AssertionError("typography must not generate a scene"))
    monkeypatch.setattr(thumbnail_server, "gen_scene", gen_scene)
    compose = Mock(return_value=Image.new("RGB", (960, 540)))
    monkeypatch.setattr(thumbnail_server, "compose", compose)
    monkeypatch.setattr(thumbnail_server, "OUT_DIR", tmp_path)
    with thumbnail_server._busy_lock:
        thumbnail_server._busy = 0

    thumbnail_server.process_job(job_id)

    assert job["status"] == "done"
    assert job.transitions == ["queued", "derive", "compose", "done"]
    gen_scene.assert_not_called()
    compose.assert_called_once_with(None, direction, None)
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
        return {
            "scene_prompt": "scene", "headline": "headline", "tag": "headline",
            "visual_style": "object", "tone": "bright-warm", "accent": [196, 166, 96],
            "kicker": "SPECIAL REPORT", "brand": thumbnail_server.DEFAULT_BRAND,
        }

    monkeypatch.setattr(thumbnail_server, "derive", blocked_derive)
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
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
        lambda *_args, **_kwargs: (derive_started.set() or {
            "scene_prompt": "scene", "headline": "headline", "tag": "headline",
            "visual_style": "object", "tone": "bright-warm", "accent": [196, 166, 96],
            "kicker": "SPECIAL REPORT", "brand": thumbnail_server.DEFAULT_BRAND,
        }),
    )
    monkeypatch.setattr(thumbnail_server, "gen_scene", lambda prompt: prompt)
    monkeypatch.setattr(thumbnail_server, "compose", lambda *_args: Mock(save=Mock()))
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


def test_compose_opaque_panel_hides_overlapping_scene_content():
    scene_color = (210, 30, 70)
    scene = Image.new("RGB", (960, 540), scene_color)

    result = thumbnail_server.compose(scene, {"tone": "bright-warm"})

    assert result.getpixel((500, 20)) == (246, 239, 222)
    assert result.getpixel((800, 20)) == scene_color


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
