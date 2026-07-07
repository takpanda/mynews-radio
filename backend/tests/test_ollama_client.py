"""Tests for OllamaClient.generate_json() num_ctx option."""

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
