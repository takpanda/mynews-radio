"""関心トピックと記事の関連度判定（LLM）と、判定結果のキャッシュ（BEEW-540 仕様 §8）。

判定は (記事, トピック) の組み合わせ単位で行う。指紋（name + description）が一致する
判定行があれば再判定しない。判定の失敗は呼び出し元で非致命として扱う前提。
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

from app.db.connection import get_db_connection
from app.prompts.service import render_prompt
from app.services.llm_call_log_service import set_llm_context
from app.services.settings_service import TopicSetting, topic_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_CHUNK_SIZE = 20
_RELEVANCE_MIN = 0
_RELEVANCE_MAX = 3


@dataclass
class JudgeStats:
    pending: int = 0  # 判定が必要だった (記事, トピック) の組み合わせ数
    stored: int = 0  # 判定結果としてキャッシュへ保存した件数
    rejected: int = 0  # 範囲外・未知のid・型不正などで捨てた件数
    failed_chunks: int = 0  # 応答が取得できなかった（または形式不正の）チャンク数


def pending_topics_by_article(
    article_ids: Sequence[int], topics: Sequence[TopicSetting]
) -> dict[int, list[TopicSetting]]:
    """現行の指紋で判定済みでない (記事, トピック) を、記事ごとに返す。判定済みの組み合わせは含めない。"""
    if not article_ids or not topics:
        return {}
    fingerprints = {topic.id: topic_fingerprint(topic.name, topic.description) for topic in topics}
    article_placeholders = ",".join("?" for _ in article_ids)
    topic_placeholders = ",".join("?" for _ in topics)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT article_id, topic_id, fingerprint FROM article_topic_matches "
            f"WHERE article_id IN ({article_placeholders}) AND topic_id IN ({topic_placeholders})",
            [*article_ids, *(topic.id for topic in topics)],
        ).fetchall()
    fresh = {
        (row["article_id"], row["topic_id"])
        for row in rows
        if fingerprints.get(row["topic_id"]) == row["fingerprint"]
    }
    pending: dict[int, list[TopicSetting]] = {}
    for article_id in article_ids:
        missing = [topic for topic in topics if (article_id, topic.id) not in fresh]
        if missing:
            pending[article_id] = missing
    return pending


def judge_pending_articles(
    client: Any,
    topics: Sequence[TopicSetting],
    articles: Sequence[dict[str, Any]],
    *,
    episode_id: int | None = None,
    program_id: str | None = None,
    chunk_size: int = DEFAULT_JUDGE_CHUNK_SIZE,
) -> JudgeStats:
    """未判定の (記事, トピック) だけを LLM で判定し、結果を保存する。

    articles は id / title / summary を持つ dict。同じ未判定トピックの組み合わせの記事をまとめて
    chunk_size 件ずつ判定するため、既に判定済みのトピックは再判定されない。
    LLM 呼び出しで例外が出た場合は、それまでに保存したチャンクを残して呼び出し元へ送出する。
    """
    stats = JudgeStats()
    if not topics or not articles:
        return stats
    articles_by_id = {article["id"]: article for article in articles}
    pending = pending_topics_by_article(list(articles_by_id), topics)
    stats.pending = sum(len(missing) for missing in pending.values())

    groups: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for article_id, missing in pending.items():
        groups[tuple(topic.id for topic in missing)].append(article_id)
    topics_by_id = {topic.id: topic for topic in topics}
    for topic_ids, article_ids in groups.items():
        group_topics = [topics_by_id[topic_id] for topic_id in topic_ids]
        for start in range(0, len(article_ids), chunk_size):
            chunk = [articles_by_id[article_id] for article_id in article_ids[start:start + chunk_size]]
            _judge_chunk(
                client, group_topics, chunk, stats,
                episode_id=episode_id, program_id=program_id,
            )

    logger.info(
        "topic judge done: pending=%d stored=%d rejected=%d failed_chunks=%d",
        stats.pending, stats.stored, stats.rejected, stats.failed_chunks,
    )
    return stats


def _judge_chunk(
    client: Any,
    topics: Sequence[TopicSetting],
    articles: Sequence[dict[str, Any]],
    stats: JudgeStats,
    *,
    episode_id: int | None,
    program_id: str | None,
) -> None:
    rendered = render_prompt(
        "judge_topic_relevance",
        {
            "topics_json": json.dumps(
                [{"topic_id": t.id, "name": t.name, "description": t.description} for t in topics],
                ensure_ascii=False,
                indent=2,
            ),
            "articles_json": json.dumps(
                [
                    {
                        "article_id": a["id"],
                        "title": a.get("title") or "",
                        "summary": a.get("summary") or "",
                    }
                    for a in articles
                ],
                ensure_ascii=False,
                indent=2,
            ),
        },
        program_id=program_id,
    )
    set_llm_context(
        client,
        phase="topic_judge",
        episode_id=episode_id,
        prompt_version_id=rendered.version_id,
    )
    response = client.generate_json(rendered.text)
    accepted = _parse_results(response, articles, topics, stats)
    if accepted is None:
        stats.failed_chunks += 1
        logger.warning("topic judge: invalid response, pairs stay pending articles=%d", len(articles))
        return
    if not accepted:
        return

    fingerprints = {topic.id: topic_fingerprint(topic.name, topic.description) for topic in topics}
    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO article_topic_matches (article_id, topic_id, relevance, fingerprint, judged_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(article_id, topic_id) DO UPDATE SET "
            "relevance = excluded.relevance, fingerprint = excluded.fingerprint, "
            "judged_at = excluded.judged_at",
            [
                (article_id, topic_id, relevance, fingerprints[topic_id])
                for (article_id, topic_id), relevance in accepted.items()
            ],
        )
    stats.stored += len(accepted)


def _parse_results(
    response: Any,
    articles: Sequence[dict[str, Any]],
    topics: Sequence[TopicSetting],
    stats: JudgeStats,
) -> dict[tuple[int, int], int] | None:
    """LLM 応答から、このチャンクで要求した組み合わせの有効な関連度だけを取り出す。

    応答の形式が不正なときは None を返す。範囲外の値や未知の id は捨てて rejected に数える。
    """
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list):
        return None
    allowed_articles = {article["id"] for article in articles}
    allowed_topics = {topic.id for topic in topics}
    accepted: dict[tuple[int, int], int] = {}
    for item in results:
        article_id = _as_int(item.get("article_id")) if isinstance(item, dict) else None
        relevance_map = item.get("relevance") if isinstance(item, dict) else None
        if article_id not in allowed_articles or not isinstance(relevance_map, dict):
            stats.rejected += 1
            continue
        for raw_topic_id, raw_relevance in relevance_map.items():
            topic_id = _as_int(raw_topic_id)
            relevance = _as_int(raw_relevance)
            if (
                topic_id not in allowed_topics
                or relevance is None
                or not _RELEVANCE_MIN <= relevance <= _RELEVANCE_MAX
            ):
                stats.rejected += 1
                continue
            accepted[(article_id, topic_id)] = relevance
    return accepted


def _as_int(value: Any) -> int | None:
    # bool は int のサブクラスなので、判定値としては除外する。
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
