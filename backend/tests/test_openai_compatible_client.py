from unittest.mock import MagicMock, patch

import pytest

from app.services.ollama_client import OpenAICompatibleClient


def _response(message):
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": message}]}
    response.raise_for_status.return_value = None
    return response


def test_api_key_is_sent_only_as_authorization_header():
    client = OpenAICompatibleClient("http://llm.internal", "local-model", api_key="secret-key")
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({"content": '{"ok": true}'})):
        assert client.generate_json("prompt") == {"ok": True}
    assert client.client.headers["Authorization"] == "Bearer secret-key"


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning", "thinking"])
def test_reasoning_fields_are_normalized_when_content_is_empty(field):
    client = OpenAICompatibleClient("http://llm.internal", "local-model")
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({
        "content": None, field: '{"ok": true}',
    })):
        assert client.generate_json("prompt") == {"ok": True}


def test_structured_content_list_is_normalized():
    client = OpenAICompatibleClient("http://llm.internal", "local-model")
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({
        "content": [{"type": "text", "text": '{"ok": '}, {"text": "true}"}],
    })):
        assert client.generate_json("prompt") == {"ok": True}
