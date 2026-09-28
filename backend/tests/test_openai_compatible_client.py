from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.ollama_client import OpenAICompatibleClient, create_llm_client
from app.services.llm_provider import ProviderConfig


def _response(message):
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": message}]}
    response.raise_for_status.return_value = None
    return response


def _http_error(status_code=400):
    response = MagicMock()
    response.status_code = status_code
    response.text = "unsupported response format"
    request = httpx.Request("POST", "http://llm.internal/v1/chat/completions")
    return httpx.HTTPStatusError("bad response", request=request, response=response)


def test_api_key_is_sent_only_as_authorization_header():
    client = OpenAICompatibleClient("http://llm.internal", "local-model", api_key="secret-key")
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({"content": '{"ok": true}'})):
        assert client.generate_json("prompt") == {"ok": True}
    assert client.client.headers["Authorization"] == "Bearer secret-key"


def test_lm_studio_uses_json_schema_response_format():
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider="lm_studio")
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({
        "content": '{"ok": true}',
    })) as post:
        assert client.generate_json("prompt") == {"ok": True}

    payload = post.call_args.kwargs["json"]
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "schema": {"type": "object", "additionalProperties": True},
        },
    }


def test_lm_studio_retries_http_400_with_text_and_records_each_attempt():
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider="lm_studio")
    with patch(
        "app.services.ollama_client.httpx.Client.post",
        side_effect=[_http_error(), _response({"content": '{"ok": true}'})],
    ) as post, patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") == {"ok": True}

    assert [call.kwargs["json"]["response_format"]["type"] for call in post.call_args_list] == [
        "json_schema", "text",
    ]
    assert [(call.kwargs["attempt"], call.kwargs["status"]) for call in record.call_args_list] == [
        (1, "retry"), (2, "success"),
    ]


def test_lm_studio_returns_none_and_logs_error_when_text_retry_fails(caplog):
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider="lm_studio")
    with patch(
        "app.services.ollama_client.httpx.Client.post",
        side_effect=[_http_error(), _http_error()],
    ) as post, patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") is None

    assert post.call_count == 2
    assert [call.kwargs["json"]["response_format"]["type"] for call in post.call_args_list] == [
        "json_schema", "text",
    ]
    assert record.call_args.kwargs["attempt"] == 2
    assert record.call_args.kwargs["status"] == "error"
    assert "OpenAI-compatible LLM request failed" in caplog.text


def test_vllm_keeps_json_object_and_does_not_retry_http_400():
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider="vllm")
    with patch(
        "app.services.ollama_client.httpx.Client.post", side_effect=_http_error(),
    ) as post, patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") is None

    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}
    assert record.call_args.kwargs["attempt"] == 1


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
def test_invalid_generated_json_is_recorded_as_json_parse_failed(provider):
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider=provider)
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({
        "content": "not valid json",
    })), patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") is None

    assert record.call_args.kwargs["status"] == "json_parse_failed"


@pytest.mark.parametrize("provider", ["lm_studio", "vllm"])
def test_http_error_is_recorded_as_error(provider):
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider=provider)
    with patch(
        "app.services.ollama_client.httpx.Client.post",
        side_effect=httpx.ConnectError("connection refused"),
    ), patch("app.services.ollama_client._record_llm_call") as record:
        assert client.generate_json("prompt") is None

    assert record.call_args.kwargs["status"] == "error"


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
