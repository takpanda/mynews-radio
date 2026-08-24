from unittest.mock import MagicMock, patch

import pytest

from app.services.ollama_client import OpenAICompatibleClient, create_llm_client
from app.services.llm_provider import ProviderConfig


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


@pytest.mark.parametrize("provider", ["lm_studio", "vllm"])
def test_provider_name_is_preserved_for_persistent_logs(provider):
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider=provider)
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({"content": '{"ok": true}'})), \
         patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") == {"ok": True}
    assert record.call_args.args[0]._provider == provider


@pytest.mark.parametrize("provider", ["lm_studio", "vllm"])
def test_create_llm_client_passes_real_provider_name(provider):
    config = ProviderConfig(provider, "http://llm.internal", "local-model", False, "")
    with patch("app.services.llm_provider.validate_provider_model", return_value=config):
        client = create_llm_client(provider, "local-model")
    assert client._provider == provider
