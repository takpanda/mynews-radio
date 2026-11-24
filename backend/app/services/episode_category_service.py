"""エピソードカテゴリの選定・検証・保存。"""

import json
import logging
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.ollama_client import OllamaClient, create_llm_client
from app.services.llm_call_log_service import infer_episode_id, set_llm_context
from app.prompts.service import program_id_for_episode, render_prompt

logger = logging.getLogger(__name__)

# 表記を固定し、アーカイブ側が安定して利用できるようにする。
EPISODE_CATEGORIES = (
    "政治・行政", "経済・金融", "社会・暮らし", "国際", "テック・IT",
    "AI・先端技術", "サイエンス・医療", "環境・エネルギー", "ビジネス",
    "セキュリティ", "エンタメ", "スポーツ", "文化・歴史", "教育", "その他",
)
_CATEGORY_SET = frozenset(EPISODE_CATEGORIES)


def validate_episode_categories(value: Any) -> list[str]:
    """LLM応答を契約（固定値、最大3件、重複なし）に正規化する。"""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        category = item.strip()
        if category in _CATEGORY_SET and category not in result:
            result.append(category)
        if len(result) >= 3:
            break
    return result


def parse_episode_categories(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    return validate_episode_categories(value)


def save_episode_categories(episode_id: int, categories: list[str]) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET categories = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(validate_episode_categories(categories), ensure_ascii=False), episode_id),
        )


def _load_category_source(script_path: str, summaries_path: str) -> str:
    try:
        script = json.loads(Path(script_path).read_text(encoding="utf-8"))
        lines = [str(line.get("text", "")).strip() for line in script.get("lines", [])]
        text = "\n".join(line for line in lines if line)
        if text:
            return text
    except (OSError, TypeError, json.JSONDecodeError):
        pass
    try:
        summaries = json.loads(Path(summaries_path).read_text(encoding="utf-8"))
        return "\n".join(
            str(item.get("summary", "")).strip()
            for item in summaries
            if isinstance(item, dict) and item.get("summary")
        )
    except (OSError, TypeError, json.JSONDecodeError):
        return ""


def select_episode_categories(
    script_path: str,
    summaries_path: str,
    *,
    client_factory: Callable[..., Any] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> list[str]:
    """台本を優先してLLMで選定する。全ての失敗は空配列として扱う。

    llm_provider / llm_model を指定した場合は台本生成と同じLLMを使う。
    未指定時のみ従来どおり既定のOllamaを使う（本番は content LLM が codex 等のため、
    Ollama固定だと接続失敗→空配列になり全回が「一般」へ落ちていた）。
    """
    source = _load_category_source(script_path, summaries_path)
    if not source:
        return []
    settings = get_settings()
    episode_id = infer_episode_id(script_path)
    rendered = render_prompt(
        "category",
        {"categories": ", ".join(EPISODE_CATEGORIES), "source": source},
        program_id=program_id_for_episode(episode_id),
    )
    try:
        # OllamaClient の既定タイムアウト（推論用の十分な時間）を利用する。
        # カテゴリ処理の失敗は下記で吸収するが、正常な推論を1秒で打ち切らない。
        if client_factory is not None:
            client_cm = client_factory(settings.ollama_base_url, settings.ollama_model, max_retries=0)
        elif llm_provider or llm_model:
            client_cm = create_llm_client(llm_provider, llm_model)
        else:
            client_cm = OllamaClient(settings.ollama_base_url, settings.ollama_model, max_retries=0)
        with client_cm as client:
            set_llm_context(
                client,
                phase="category",
                episode_id=episode_id,
                prompt_version_id=rendered.version_id,
            )
            response = client.generate_json(rendered.text)
        if not isinstance(response, dict):
            return []
        return validate_episode_categories(response.get("categories", response.get("category", [])))
    except Exception:
        logger.warning("episode category selection failed (non-fatal)", exc_info=True)
        return []
