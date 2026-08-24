"""LLM呼び出しの永続ログ。

生成処理の主経路から独立したbest-effort副作用として実装する。ログ保存の
失敗は、LLM生成の成否や既存の生成フローへ伝播させない。
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
JSONL_FILENAME = "llm_calls.jsonl"
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer\s+)?|bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;}]+"),
    re.compile(r"(?i)(x-api-key|api-key)\s*[:=]\s*[^\s,;}]+"),
)


def sanitize_llm_text(value: Any) -> str:
    """保存対象テキストから認証情報らしき値をマスクする。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    try:
        settings = get_settings()
        for secret in (
            settings.api_key,
            settings.lm_studio_api_key,
            settings.vllm_api_key,
            settings.telegram_bot_token,
        ):
            if secret:
                text = text.replace(secret, "[REDACTED]")
    except Exception:
        # 設定取得失敗時も、パターンベースのマスクは継続する。
        pass
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def infer_episode_id(path: str | os.PathLike[str] | None) -> int | None:
    """生成成果物のパスから、現在のエピソードIDを推定する。

    ``data/episodes/{id}`` 配下のファイルだけを対象とし、単独実行の要約など
    エピソードに紐付かない呼び出しは ``None`` を返す。
    """
    if not path:
        return None
    parts = Path(path).parts
    for index, part in enumerate(parts):
        if part == "episodes" and index + 1 < len(parts):
            candidate = parts[index + 1]
            if candidate.isdigit():
                return int(candidate)
    return None


def set_llm_context(client: Any, *, phase: str, episode_id: int | None = None) -> None:
    """既存のクライアント呼び出しを変更せず、ログ用コンテキストを設定する。"""
    setattr(client, "_generation_context", {"phase": phase, "episode_id": episode_id})


def _jsonl_path(episode_id: int) -> Path:
    root = os.getenv("EPISODES_DIR", os.path.join("data", "episodes"))
    return Path(root) / str(episode_id) / JSONL_FILENAME


def llm_jsonl_path(episode_id: int) -> Path:
    """指定エピソードのJSONL保存先を返す（APIのダウンロード用）。"""
    return _jsonl_path(episode_id)


def _safe_context(client: Any) -> dict[str, Any]:
    context = getattr(client, "_generation_context", {}) or {}
    return {
        "episode_id": context.get("episode_id"),
        "phase": context.get("phase") or "unknown",
        "provider": context.get("provider") or ("ollama" if client.__class__.__name__ == "OllamaClient" else "unknown"),
        "model": context.get("model") or getattr(client, "_model", ""),
        "base_url": context.get("base_url") or getattr(client, "_base_url", ""),
    }


def record_llm_call(
    client: Any,
    *,
    attempt: int,
    status: str,
    prompt_text: Any,
    response_text: Any = "",
    thinking_text: Any = "",
    latency_ms: int | None = None,
) -> str | None:
    """DBとエピソード別JSONLへ1試行を保存する。常に例外を外へ出さない。"""
    try:
        context = _safe_context(client)
        call_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        item = {
            "call_id": call_id,
            "episode_id": context["episode_id"],
            "phase": context["phase"],
            "provider": context["provider"],
            "model": sanitize_llm_text(context["model"]),
            "base_url": sanitize_llm_text(context["base_url"]),
            "attempt": attempt,
            "status": status,
            "latency_ms": latency_ms,
            "prompt_text": sanitize_llm_text(prompt_text),
            "response_text": sanitize_llm_text(response_text),
            "thinking_text": sanitize_llm_text(thinking_text),
            "created_at": created_at,
        }

        # DBとJSONLは独立した副作用。片方の障害で他方を失わない。
        try:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO llm_call_logs "
                    "(call_id, episode_id, phase, provider, model, base_url, attempt, status, "
                    "latency_ms, prompt_text, response_text, thinking_text, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(item[key] for key in (
                        "call_id", "episode_id", "phase", "provider", "model", "base_url",
                        "attempt", "status", "latency_ms", "prompt_text", "response_text",
                        "thinking_text", "created_at",
                    )),
                )
        except Exception:
            logger.warning("LLM call DB log failed (call_id=%s)", call_id, exc_info=True)

        episode_id = context["episode_id"]
        if episode_id is not None:
            try:
                path = _jsonl_path(int(episode_id))
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            except Exception:
                logger.warning("LLM call JSONL log failed (call_id=%s)", call_id, exc_info=True)
        return call_id
    except Exception:
        logger.warning("LLM call log construction failed", exc_info=True)
        return None


def list_llm_call_metadata(conn: Any, episode_id: int, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, call_id, episode_id, phase, provider, model, base_url, attempt, status, "
        "latency_ms, created_at FROM llm_call_logs WHERE episode_id = ? "
        "ORDER BY created_at ASC, id ASC LIMIT ?",
        (episode_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_llm_call(conn: Any, episode_id: int, call_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, call_id, episode_id, phase, provider, model, base_url, attempt, status, "
        "latency_ms, prompt_text, response_text, thinking_text, created_at "
        "FROM llm_call_logs WHERE episode_id = ? AND call_id = ?",
        (episode_id, call_id),
    ).fetchone()
    return dict(row) if row else None


def cleanup_llm_call_logs(now: datetime | None = None) -> int:
    """DBとJSONLのLLMログを90日TTLで削除し、削除したDB行数を返す。"""
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=RETENTION_DAYS)
    cutoff_iso = cutoff.isoformat()
    deleted = 0
    try:
        with get_db_connection() as conn:
            result = conn.execute(
                "DELETE FROM llm_call_logs WHERE julianday(created_at) < julianday(?)",
                (cutoff_iso,),
            )
            deleted = result.rowcount if result.rowcount != -1 else 0
    except Exception:
        logger.warning("LLM call DB cleanup failed", exc_info=True)

    root = Path(os.getenv("EPISODES_DIR", os.path.join("data", "episodes")))
    if not root.is_dir():
        return deleted
    for path in root.glob(f"*/{JSONL_FILENAME}"):
        try:
            kept: list[str] = []
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                        created = datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00"))
                        if created >= cutoff:
                            kept.append(line)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        # 壊れた行は分析不能なため、TTL処理で除去する。
                        continue
            if kept:
                path.write_text("".join(kept), encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        except Exception:
            logger.warning("LLM call JSONL cleanup failed path=%s", path, exc_info=True)
    return deleted
