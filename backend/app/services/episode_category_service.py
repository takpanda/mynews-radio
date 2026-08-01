"""エピソードカテゴリの選定・検証・保存。"""

import json
import logging
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.ollama_client import OllamaClient

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
    client_factory: Callable[..., OllamaClient] = OllamaClient,
) -> list[str]:
    """台本を優先してLLMで選定する。全ての失敗は空配列として扱う。"""
    source = _load_category_source(script_path, summaries_path)
    if not source:
        return []
    settings = get_settings()
    prompt = f"""あなたはニュース番組の分類担当です。次の内容に該当するカテゴリを0〜3件選んでください。
必ずJSONオブジェクト {{\"categories\": [\"カテゴリ\"]}} のみを返してください。
カテゴリは次の固定15件から選び、重複させないでください: {', '.join(EPISODE_CATEGORIES)}
「テック・IT」は一般的なIT製品、ソフトウェア、通信、デジタルサービスを指します。
「AI・先端技術」は生成AI、機械学習、ロボット、量子技術など、先端技術そのものが主題の場合に限ります。

内容:
{source}
"""
    try:
        with client_factory(settings.ollama_base_url, settings.ollama_model, max_retries=0, timeout=1.0) as client:
            response = client.generate_json(prompt)
        if not isinstance(response, dict):
            return []
        return validate_episode_categories(response.get("categories", response.get("category", [])))
    except Exception:
        logger.warning("episode category selection failed (non-fatal)", exc_info=True)
        return []
