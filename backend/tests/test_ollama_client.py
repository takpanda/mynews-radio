"""Tests for OllamaClient.generate_json()."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.ollama_client import OllamaClient


def _make_client(model: str = "qwen2.5:7b") -> OllamaClient:
    return OllamaClient(base_url="http://localhost:11434", model=model, max_retries=1)


def _mock_post_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.json = lambda: {"response": '{"ok": true}'}
    mock.raise_for_status = lambda: None
    return mock


def _mock_post_response_with(data):
    mock = MagicMock()
    mock.status_code = 200
    mock.json = lambda: data
    mock.raise_for_status = lambda: None
    return mock


@pytest.fixture(autouse=True)
def _clear_num_ctx_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)


class TestGenerateJsonNumCtx:
    """generate_json() sends the configured options.num_ctx in the payload."""

    def test_num_ctx_defaults_to_32768(self, monkeypatch):
        """OLLAMA_NUM_CTX 未設定時は num_ctx=32768 が設定されること"""
        monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
        client = _make_client()
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["num_ctx"] == 32768

    def test_num_ctx_can_be_overridden_by_environment(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
        client = _make_client()
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["num_ctx"] == 16384

    @pytest.mark.parametrize("value", ["", "abc", "0", "-1", "3.5", "  "])
    def test_num_ctx_invalid_environment_falls_back_to_default(self, monkeypatch, value):
        monkeypatch.setenv("OLLAMA_NUM_CTX", value)
        client = _make_client()
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["num_ctx"] == 32768

    def test_num_ctx_merges_with_existing_options(self):
        """2: options に他のキーが既にある場合 → 既存キーを保持したまま num_ctx が追加されること"""
        payload = {"model": "test", "prompt": "hello", "stream": False}
        payload["options"] = {"seed": 42, "temperature": 0.7}

        options = payload.get("options", {})
        options["num_ctx"] = 32768
        payload["options"] = options

        assert payload["options"]["num_ctx"] == 32768
        assert payload["options"]["seed"] == 42
        assert payload["options"]["temperature"] == 0.7
        assert len(payload["options"]) == 3

    def test_num_ctx_with_json_format(self):
        """3: format: json が有効な場合も num_ctx が設定されること"""
        client = _make_client(model="qwen2.5:7b")
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload.get("format") == "json"
        assert payload["options"]["num_ctx"] == 32768

    def test_num_ctx_with_ornith_model(self):
        """4: ornith モデルで format: json がスキップされる場合も num_ctx が設定されること"""
        client = _make_client(model="ornith:latest")
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert "format" not in payload
        assert payload["options"]["num_ctx"] == 32768


class TestGenerateJson:
    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_use_generate_with_top_level_thinking_disabled_and_json_format(self, model):
        """Qwen3 と非Qwen3で endpoint と必須payloadを統一する。"""
        client = _make_client(model=model)
        response = _mock_post_response()

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_args.args[0] == "/api/generate"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["prompt"] == "hello"
        assert "messages" not in payload
        assert payload["format"] == "json"
        assert payload["think"] is False
        assert payload["options"]["num_ctx"] == 32768
        assert "think" not in payload["options"]

    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_fall_back_to_thinking_when_response_is_empty(self, model):
        client = _make_client(model=model)
        response = _mock_post_response_with(
            {"response": "", "thinking": '<|channel|>output{"ok": true}<|channel|>'}
        )

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_count == 1

    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_return_failure_for_invalid_json_after_bounded_retries(self, model):
        client = OllamaClient(
            base_url="http://localhost:11434",
            model=model,
            max_retries=1,
        )
        response = _mock_post_response_with(
            {
                "response": "not valid json",
                "thinking": "",
            }
        )

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") is None

        assert mock_post.call_count == 2

    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_do_not_fall_back_when_response_is_thinking_artifact(self, model):
        client = OllamaClient(
            base_url="http://localhost:11434",
            model=model,
            max_retries=0,
        )
        response = _mock_post_response_with(
            {
                "response": '{"thought": "reasoning"}',
                "thinking": '<|channel|>output{"ok": true}<|channel|>',
            }
        )

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") is None

        assert mock_post.call_count == 1

    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_retry_with_forced_json_prompt_after_empty_response(self, model):
        client = _make_client(model=model)
        empty_response = _mock_post_response_with({"response": "", "thinking": ""})
        valid_response = _mock_post_response()

        with patch(
            "app.services.ollama_client.httpx.Client.post",
            side_effect=[empty_response, valid_response],
        ) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_count == 2
        retry_payload = mock_post.call_args_list[1].kwargs["json"]
        assert retry_payload["prompt"].startswith("Answer with ONLY valid JSON")

    @pytest.mark.parametrize("model", ["qwen3.8:latest", "qwen2.5:7b"])
    def test_models_return_failure_after_bounded_timeout_retries(self, model):
        client = OllamaClient(
            base_url="http://localhost:11434",
            model=model,
            max_retries=1,
            timeout=httpx.Timeout(0.01),
        )
        timeout_error = httpx.ReadTimeout("timed out")

        with patch(
            "app.services.ollama_client.httpx.Client.post",
            side_effect=timeout_error,
        ) as mock_post:
            assert client.generate_json("hello") is None

        assert mock_post.call_count == 2

    def test_default_timeout_keeps_legacy_600_seconds(self):
        client = OllamaClient(base_url="http://localhost:11434", model="qwen3.8:latest")

        assert client._timeout == 600.0
