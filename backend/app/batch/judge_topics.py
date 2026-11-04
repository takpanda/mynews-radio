import logging
import os
from typing import Sequence

from app.config import get_settings
from app.prompts.service import program_id_for_episode
from app.services.article_service import ArticleService
from app.services.ollama_client import OllamaClient, create_llm_client
from app.services.settings_service import TopicSetting
from app.services.topic_relevance_service import (
    DEFAULT_JUDGE_CHUNK_SIZE,
    JudgeStats,
    judge_pending_articles,
)

logger = logging.getLogger(__name__)


def _judge_chunk_size() -> int:
    raw = os.getenv("TOPIC_JUDGE_CHUNK_SIZE")
    try:
        value = int(raw) if raw else DEFAULT_JUDGE_CHUNK_SIZE
    except ValueError:
        return DEFAULT_JUDGE_CHUNK_SIZE
    return value if value >= 1 else DEFAULT_JUDGE_CHUNK_SIZE


def judge_topics(
    *,
    topics: Sequence[TopicSetting],
    source: str | None,
    min_importance: int,
    priority_themes: Sequence[str] = (),
    excluded_themes: Sequence[str] = (),
    episode_id: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> JudgeStats:
    """直近の候補記事について、有効なトピックとの関連度を判定してキャッシュする。"""
    if not topics:
        return JudgeStats()

    settings = get_settings()
    articles = ArticleService().fetch_topic_judge_candidates(
        min_importance_score=min_importance,
        source=source,
        priority_themes=list(priority_themes),
        excluded_themes=list(excluded_themes),
    )
    if not articles:
        logger.info("No candidate articles for topic judge")
        return JudgeStats()

    program_id = program_id_for_episode(episode_id)
    client_factory = (
        (lambda: create_llm_client(llm_provider, llm_model))
        if (llm_provider or llm_model)
        else (lambda: OllamaClient(settings.ollama_base_url, settings.ollama_model))
    )
    with client_factory() as client:
        return judge_pending_articles(
            client,
            topics,
            articles,
            episode_id=episode_id,
            program_id=program_id,
            chunk_size=_judge_chunk_size(),
        )

