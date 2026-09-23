import base64
import json
import os
import time
from unittest.mock import MagicMock, patch

from app.services.codex_client import CodexClient
from app.services.codex_token_store import CodexTokenStore
from app.services.llm_call_log_service import sanitize_llm_text


def _jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def _response(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _stream_response(status_code: int, *events: str) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.iter_lines.side_effect = lambda: iter(events)
    stream = MagicMock()
    stream.__enter__.return_value = response
    return stream


def _delta(text: str) -> str:
    return f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': text})}"


def test_responses_request_extracts_json_without_response_format():
    client = CodexClient("https://chatgpt.com/backend-api/codex", "gpt-5.4", "access", "refresh")
    stream_response = _stream_response(200, _delta('{"ok":'), _delta(" true}"), "data: [DONE]")

    with patch("app.services.codex_client.httpx.Client.stream", return_value=stream_response) as stream:
        assert client.generate_json("summarize this") == {"ok": True}

    payload = stream.call_args.kwargs["json"]
    assert payload["model"] == "gpt-5.4"
    assert isinstance(payload["input"], list)
    assert payload["input"][0]["role"] == "user"
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    input_text = payload["input"][0]["content"][0]["text"]
    assert input_text.startswith("summarize this\n\n")
    assert "JSON" in input_text
    assert payload["stream"] is True
    assert "response_format" not in payload


def test_expiring_access_token_is_refreshed_and_rotated_token_is_used():
    old_access = _jwt(int(time.time()) - 1)
    new_access = _jwt(int(time.time()) + 3600)
    client = CodexClient("https://chatgpt.com/backend-api/codex", "gpt-5.4", old_access, "old-refresh")
    refresh = _response(200, {"access_token": new_access, "refresh_token": "new-refresh"})
    generation = _stream_response(200, _delta('{"ok": true}'))

    with patch("app.services.codex_client.httpx.Client.post", return_value=refresh), patch(
        "app.services.codex_client.httpx.Client.stream", return_value=generation
    ):
        assert client.generate_json("prompt") == {"ok": True}

    assert client._access_token == new_access
    assert client._refresh_token == "new-refresh"


def test_401_refreshes_once_and_retries():
    client = CodexClient("https://chatgpt.com/backend-api/codex", "gpt-5.4", "access", "refresh")
    unauthorized = _stream_response(401)
    refresh = _response(200, {"access_token": "new-access"})
    generation = _stream_response(200, _delta('{"ok": true}'))

    with patch("app.services.codex_client.httpx.Client.post", return_value=refresh) as post, patch(
        "app.services.codex_client.httpx.Client.stream", side_effect=[unauthorized, generation]
    ) as stream:
        assert client.generate_json("prompt") == {"ok": True}

    assert post.call_count == 1
    assert stream.call_count == 2


def test_rotated_pair_is_reused_by_a_new_client_from_shared_store(tmp_path):
    store_path = tmp_path / "codex_tokens.json"
    old_access = _jwt(int(time.time()) - 1)
    new_access = _jwt(int(time.time()) + 3600)
    first_client = CodexClient(
        "https://chatgpt.com/backend-api/codex",
        "gpt-5.4",
        old_access,
        "old-refresh",
        token_store_path=str(store_path),
    )
    refresh = _response(200, {"access_token": new_access, "refresh_token": "new-refresh"})
    generation = _stream_response(200, _delta('{"ok": true}'))

    with patch("app.services.codex_client.httpx.Client.post", return_value=refresh), patch(
        "app.services.codex_client.httpx.Client.stream", return_value=generation
    ):
        assert first_client.generate_json("prompt") == {"ok": True}

    second_client = CodexClient(
        "https://chatgpt.com/backend-api/codex",
        "gpt-5.4",
        old_access,
        "old-refresh",
        token_store_path=str(store_path),
    )
    assert second_client._access_token == new_access
    assert second_client._refresh_token == "new-refresh"
    assert os.stat(store_path).st_mode & 0o777 == 0o600

    with patch("app.services.codex_client.httpx.Client.stream", return_value=generation) as stream:
        assert second_client.generate_json("next phase") == {"ok": True}
    assert stream.call_count == 1


def test_missing_credentials_does_not_make_request():
    client = CodexClient("https://chatgpt.com/backend-api/codex", "gpt-5.4", "", "")
    with patch("app.services.codex_client.httpx.Client.stream") as stream:
        assert client.generate_json("prompt") is None
    stream.assert_not_called()


def test_codex_tokens_are_redacted_from_persistent_log_text(monkeypatch):
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "access-secret")
    monkeypatch.setenv("CODEX_REFRESH_TOKEN", "refresh-secret")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        text = sanitize_llm_text("access-secret refresh-secret")
    finally:
        get_settings.cache_clear()

    assert "access-secret" not in text
    assert "refresh-secret" not in text


def test_rotated_store_tokens_are_redacted_from_persistent_log_text(tmp_path, monkeypatch):
    store_path = tmp_path / "codex_tokens.json"
    CodexTokenStore(str(store_path)).load_or_initialize("rotated-access", "rotated-refresh")
    monkeypatch.setenv("CODEX_TOKEN_STORE_PATH", str(store_path))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        text = sanitize_llm_text("rotated-access rotated-refresh")
    finally:
        get_settings.cache_clear()

    assert "rotated-access" not in text
    assert "rotated-refresh" not in text
