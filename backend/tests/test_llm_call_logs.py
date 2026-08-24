"""LLM呼び出しログの保存・閲覧・TTLの確認。"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.db.connection import get_db_connection
from app.services.llm_call_log_service import cleanup_llm_call_logs, record_llm_call, set_llm_context
from app.services.ollama_client import OllamaClient, OpenAICompatibleClient


def _episode() -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO episodes (episode_date, status) VALUES (?, ?)",
            ("2026-08-24", "generating"),
        )
        return cursor.lastrowid


def _response(data: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = data
    return response


def test_record_llm_call_writes_db_and_episode_jsonl_without_secret(tmp_path, monkeypatch):
    episode_id = _episode()
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "episodes"))
    client = OllamaClient("http://ollama.local", "model")
    set_llm_context(client, phase="script", episode_id=episode_id)

    call_id = record_llm_call(
        client,
        attempt=1,
        status="success",
        prompt_text="Authorization: Bearer top-secret\napi_key=hidden prompt",
        response_text='{"ok": true}',
        thinking_text="thinking",
        latency_ms=12,
    )

    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM llm_call_logs WHERE call_id = ?", (call_id,)).fetchone()
    assert row["episode_id"] == episode_id
    assert row["phase"] == "script"
    assert "top-secret" not in row["prompt_text"]
    assert "hidden" not in row["prompt_text"]

    jsonl = tmp_path / "episodes" / str(episode_id) / "llm_calls.jsonl"
    item = json.loads(jsonl.read_text(encoding="utf-8"))
    assert item["call_id"] == call_id
    assert item["response_text"] == '{"ok": true}'


def test_standalone_call_keeps_episode_null_and_does_not_create_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "custom-episodes"))
    client = OllamaClient("http://ollama.local", "model")
    set_llm_context(client, phase="summarize", episode_id=None)

    call_id = record_llm_call(client, attempt=1, status="success", prompt_text="standalone")
    with get_db_connection() as conn:
        row = conn.execute("SELECT episode_id FROM llm_call_logs WHERE call_id = ?", (call_id,)).fetchone()
    assert row["episode_id"] is None
    assert not (tmp_path / "custom-episodes" / "llm_calls.jsonl").exists()


def test_custom_episodes_dir_path_still_infers_episode_id(tmp_path, monkeypatch):
    episode_id = 42
    episodes_dir = tmp_path / "custom-episodes"
    monkeypatch.setenv("EPISODES_DIR", str(episodes_dir))
    script_path = episodes_dir / str(episode_id) / "script.json"
    from app.services.llm_call_log_service import infer_episode_id
    client = OllamaClient("http://ollama.local", "model")
    set_llm_context(client, phase="script", episode_id=infer_episode_id(script_path))
    # 呼び出し元と同じ推定方式で、カスタムEPISODES_DIR配下を紐付ける。
    assert infer_episode_id(script_path) == episode_id
    call_id = record_llm_call(client, attempt=1, status="success", prompt_text="script")
    jsonl = episodes_dir / str(episode_id) / "llm_calls.jsonl"
    assert jsonl.is_file()
    assert call_id in jsonl.read_text(encoding="utf-8")


def test_generate_json_records_retry_and_success(tmp_path, monkeypatch):
    episode_id = _episode()
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "episodes"))
    client = OllamaClient("http://ollama.local", "model", max_retries=1)
    set_llm_context(client, phase="correction", episode_id=episode_id)
    with patch(
        "app.services.ollama_client.httpx.Client.post",
        side_effect=[_response({"response": "broken", "thinking": ""}), _response({"response": '{"ok": true}'})],
    ):
        assert client.generate_json("prompt") == {"ok": True}

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT status, attempt, prompt_text FROM llm_call_logs WHERE episode_id = ? ORDER BY id",
            (episode_id,),
        ).fetchall()
    assert [(row["status"], row["attempt"]) for row in rows] == [("retry", 1), ("success", 2)]
    assert rows[0]["prompt_text"] == "prompt"


@pytest.mark.parametrize("provider", ["lm_studio", "vllm"])
def test_openai_compatible_parse_failure_is_persisted_to_db_and_jsonl(tmp_path, monkeypatch, provider):
    episode_id = _episode()
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "episodes"))
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider=provider)
    set_llm_context(client, phase="script", episode_id=episode_id)

    with patch(
        "app.services.ollama_client.httpx.Client.post",
        return_value=_response({"choices": [{"message": {"content": "not valid json"}}]}),
    ):
        assert client.generate_json("prompt") is None

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT provider, status FROM llm_call_logs WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
    assert (row["provider"], row["status"]) == (provider, "json_parse_failed")

    jsonl = tmp_path / "episodes" / str(episode_id) / "llm_calls.jsonl"
    item = json.loads(jsonl.read_text(encoding="utf-8"))
    assert (item["provider"], item["status"]) == (provider, "json_parse_failed")


@pytest.mark.parametrize("provider", ["lm_studio", "vllm"])
def test_openai_compatible_http_failure_is_persisted_as_error(tmp_path, monkeypatch, provider):
    episode_id = _episode()
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "episodes"))
    client = OpenAICompatibleClient("http://llm.internal", "local-model", provider=provider)
    set_llm_context(client, phase="script", episode_id=episode_id)

    with patch(
        "app.services.ollama_client.httpx.Client.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        assert client.generate_json("prompt") is None

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT provider, status FROM llm_call_logs WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
    assert (row["provider"], row["status"]) == (provider, "error")

    jsonl = tmp_path / "episodes" / str(episode_id) / "llm_calls.jsonl"
    item = json.loads(jsonl.read_text(encoding="utf-8"))
    assert (item["provider"], item["status"]) == (provider, "error")


def test_log_write_failure_does_not_fail_generation():
    client = OllamaClient("http://ollama.local", "model", max_retries=0)
    with patch("app.services.ollama_client.httpx.Client.post", return_value=_response({"response": '{"ok": true}'})), \
         patch("app.services.ollama_client.record_llm_call", side_effect=OSError("disk full")):
        assert client.generate_json("prompt") == {"ok": True}


def test_llm_call_api_hides_body_from_list_and_allows_detail_and_download(client):
    episode_id = _episode()
    ollama = OllamaClient("http://ollama.local", "model")
    set_llm_context(ollama, phase="review", episode_id=episode_id)
    call_id = record_llm_call(
        ollama,
        attempt=1,
        status="success",
        prompt_text="full prompt",
        response_text="full response",
        thinking_text="full thinking",
    )

    listing = client.get(f"/admin/episodes/{episode_id}/llm-calls")
    assert listing.status_code == 200
    assert listing.json()["calls"][0]["call_id"] == call_id
    assert "prompt_text" not in listing.text
    assert "response_text" not in listing.text

    detail = client.get(f"/admin/episodes/{episode_id}/llm-calls/{call_id}")
    assert detail.status_code == 200
    assert detail.json()["prompt_text"] == "full prompt"
    download = client.get(f"/admin/episodes/{episode_id}/llm-calls/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/x-ndjson")
    assert call_id in download.text


def test_cleanup_llm_call_logs_removes_db_and_jsonl_entries(tmp_path, monkeypatch):
    episode_id = _episode()
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path / "episodes"))
    path = tmp_path / "episodes" / str(episode_id)
    path.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO llm_call_logs "
            "(call_id, episode_id, phase, provider, model, base_url, attempt, status, created_at) "
            "VALUES (?, ?, 'script', 'ollama', 'm', 'http://m', 1, 'success', ?)",
            ("old-call", episode_id, old),
        )
        conn.execute(
            "INSERT INTO llm_call_logs "
            "(call_id, episode_id, phase, provider, model, base_url, attempt, status, created_at) "
            "VALUES (?, ?, 'script', 'ollama', 'm', 'http://m', 1, 'success', ?)",
            ("new-call", episode_id, new),
        )
    (path / "llm_calls.jsonl").write_text(
        json.dumps({"call_id": "old-call", "created_at": old}) + "\n"
        + json.dumps({"call_id": "new-call", "created_at": new}) + "\n",
        encoding="utf-8",
    )

    assert cleanup_llm_call_logs(now=datetime.now(timezone.utc)) == 1
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llm_call_logs WHERE call_id = 'old-call'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM llm_call_logs WHERE call_id = 'new-call'").fetchone()[0] == 1
    assert "old-call" not in (path / "llm_calls.jsonl").read_text(encoding="utf-8")
