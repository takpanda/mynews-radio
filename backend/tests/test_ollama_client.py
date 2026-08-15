"""Tests for OllamaClient.generate_json()."""

from unittest.mock import MagicMock, patch

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


class TestGenerateJsonNumCtx:
    """generate_json() sends options.num_ctx=65536 in the payload."""

    def test_num_ctx_set_when_no_options(self):
        """1: options 未指定時 → num_ctx=65536 が設定されること"""
        client = _make_client()
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["num_ctx"] == 65536

    def test_num_ctx_merges_with_existing_options(self):
        """2: options に他のキーが既にある場合 → 既存キーを保持したまま num_ctx が追加されること"""
        payload = {"model": "test", "prompt": "hello", "stream": False}
        payload["options"] = {"seed": 42, "temperature": 0.7}

        options = payload.get("options", {})
        options["num_ctx"] = 65536
        payload["options"] = options

        assert payload["options"]["num_ctx"] == 65536
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
        assert payload["options"]["num_ctx"] == 65536

    def test_num_ctx_with_ornith_model(self):
        """4: ornith モデルで format: json がスキップされる場合も num_ctx が設定されること"""
        client = _make_client(model="ornith:latest")
        with patch("app.services.ollama_client.httpx.Client.post",
                   return_value=_mock_post_response()) as mock_post:
            client.generate_json("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert "format" not in payload
        assert payload["options"]["num_ctx"] == 65536


class TestGenerateJsonQwen3Chat:
    def test_qwen3_uses_chat_with_thinking_and_json_format(self):
        client = _make_client(model="qwen3.8:latest")
        response = _mock_post_response_with({"message": {"content": '{"ok": true}'}})

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_args.args[0] == "/api/chat"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["messages"] == [{"role": "user", "content": "hello"}]
        assert payload["think"] is True
        assert payload["format"] == "json"
        assert payload["options"]["num_ctx"] == 65536

    def test_qwen3_falls_back_to_thinking_when_content_is_empty(self):
        client = _make_client(model="qwen3.8:latest")
        response = _mock_post_response_with(
            {"message": {"content": "", "thinking": '<|channel|>output{"ok": true}<|channel|>'}}
        )

        with patch("app.services.ollama_client.httpx.Client.post", return_value=response) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_count == 1

    def test_non_qwen3_model_keeps_generate_endpoint(self):
        client = _make_client(model="qwen2.5:7b")

        with patch("app.services.ollama_client.httpx.Client.post", return_value=_mock_post_response()) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_args.args[0] == "/api/generate"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["prompt"] == "hello"
        assert "messages" not in payload

    def test_qwen3_retries_with_forced_json_prompt_after_empty_response(self):
        client = _make_client(model="qwen3.8:latest")
        empty_response = _mock_post_response_with({"message": {"content": "", "thinking": ""}})
        valid_response = _mock_post_response_with({"message": {"content": '{"ok": true}'}})

        with patch(
            "app.services.ollama_client.httpx.Client.post",
            side_effect=[empty_response, valid_response],
        ) as mock_post:
            assert client.generate_json("hello") == {"ok": True}

        assert mock_post.call_count == 2
        retry_payload = mock_post.call_args_list[1].kwargs["json"]
        assert retry_payload["messages"][0]["content"].startswith("Answer with ONLY valid JSON")
