import json
import re
from pathlib import Path

import httpx
import pytest

from app.prompts.service import render_prompt
from app.services.ollama_client import OllamaClient
from app.services.settings_service import TopicSetting, topic_fingerprint
from app.services.topic_relevance_service import judge_pending_articles, pending_topics_by_article


@pytest.fixture
def judge_db(monkeypatch, tmp_path):
    db_path = tmp_path / "judge.db"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    from app.db import connection
    monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    with connection.get_db_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    return connection


class FakeJudgeClient:
    """判定プロンプトに含まれる article_id / topic_id を読み、relevance_of の値で応答する。"""

    def __init__(self, relevance_of=lambda article_id, topic_id: 3):
        self.relevance_of = relevance_of
        self.prompts: list[str] = []

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        article_ids = [int(x) for x in re.findall(r'"article_id": (\d+)', prompt)]
        topic_ids = [int(x) for x in re.findall(r'"topic_id": (\d+)', prompt)]
        return {
            "results": [
                {
                    "article_id": article_id,
                    "relevance": {str(topic_id): self.relevance_of(article_id, topic_id) for topic_id in topic_ids},
                }
                for article_id in article_ids
            ]
        }


def _topic(topic_id, name="ローカルLLM", description="Ollama", weight="high"):
    return TopicSetting(topic_id, name, description, weight)


def _articles(*ids):
    return [{"id": article_id, "title": f"記事{article_id}", "summary": f"要約{article_id}"} for article_id in ids]


def _rows(db):
    with db.get_db_connection() as conn:
        return {
            (row["article_id"], row["topic_id"]): (row["relevance"], row["fingerprint"])
            for row in conn.execute("SELECT * FROM article_topic_matches")
        }


def test_second_run_does_not_call_llm(judge_db):
    topics = [_topic(1), _topic(2, name="量子化", weight="low")]
    articles = _articles(10, 11, 12)
    client = FakeJudgeClient()

    first = judge_pending_articles(client, topics, articles)
    assert (first.pending, first.stored) == (6, 6)
    calls_after_first = len(client.prompts)

    second = judge_pending_articles(client, topics, articles)
    assert second.pending == 0
    assert len(client.prompts) == calls_after_first


def test_name_or_description_change_rejudges_but_weight_change_does_not(judge_db):
    topic = _topic(1)
    articles = _articles(10, 11)
    client = FakeJudgeClient()
    judge_pending_articles(client, [topic], articles)

    weight_changed = _topic(1, weight="low")
    assert pending_topics_by_article([10, 11], [weight_changed]) == {}

    renamed = _topic(1, name="ローカル推論")
    stats = judge_pending_articles(client, [renamed], articles)
    assert stats.pending == 2
    assert stats.stored == 2
    fingerprints = {fp for _, fp in _rows(judge_db).values()}
    assert fingerprints == {topic_fingerprint("ローカル推論", "Ollama")}


def test_added_topic_judges_only_new_pairs(judge_db):
    existing = _topic(1)
    articles = _articles(10, 11)
    client = FakeJudgeClient(relevance_of=lambda a, t: 2)
    judge_pending_articles(client, [existing], articles)
    before = _rows(judge_db)

    added = _topic(2, name="自動運転", description="", weight="medium")
    prompts_before = len(client.prompts)
    stats = judge_pending_articles(client, [existing, added], articles)

    assert stats.pending == 2
    new_prompt = client.prompts[prompts_before]
    assert '"topic_id": 2' in new_prompt
    assert '"topic_id": 1' not in new_prompt
    after = _rows(judge_db)
    assert {key: after[key] for key in before} == before
    assert after[(10, 2)][0] == 2


def test_invalid_response_keeps_pairs_pending_without_raising(judge_db):
    topics = [_topic(1)]
    articles = _articles(10)
    client = FakeJudgeClient()
    client.generate_json = lambda prompt: None

    stats = judge_pending_articles(client, topics, articles)

    assert stats.failed_chunks == 1
    assert stats.stored == 0
    assert _rows(judge_db) == {}
    assert pending_topics_by_article([10], topics) == {10: topics}


def test_out_of_range_and_unknown_ids_are_not_stored(judge_db):
    topics = [_topic(1)]
    client = FakeJudgeClient()
    client.generate_json = lambda prompt: {
        "results": [
            {"article_id": 10, "relevance": {"1": 7, "99": 3}},
            {"article_id": 999, "relevance": {"1": 3}},
            {"article_id": 11, "relevance": {"1": "abc"}},
            {"article_id": 12, "relevance": {"1": True}},
            {"article_id": 13, "relevance": {"1": 1}},
            "not-a-dict",
        ]
    }

    stats = judge_pending_articles(client, topics, _articles(10, 11, 12, 13))

    assert _rows(judge_db) == {(13, 1): (1, topic_fingerprint("ローカルLLM", "Ollama"))}
    assert stats.stored == 1
    assert stats.rejected == 6


def test_chunks_split_by_chunk_size(judge_db):
    client = FakeJudgeClient()
    judge_pending_articles(client, [_topic(1)], _articles(1, 2, 3, 4, 5), chunk_size=2)

    assert len(client.prompts) == 3
    assert '"article_id": 5' in client.prompts[-1]


def test_judge_call_is_logged_to_llm_call_logs_with_topic_judge_phase(judge_db):
    seen_prompts = []

    def handler(request):
        body = json.loads(request.content)
        seen_prompts.append(body["prompt"])
        results = [
            {"article_id": 10, "relevance": {"1": 3}},
            {"article_id": 999, "relevance": {"1": 3}},
        ]
        return httpx.Response(200, json={"response": json.dumps({"results": results}), "thinking": ""})

    client = OllamaClient("http://ollama.test", "test-model", max_retries=0)
    client._client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))

    stats = judge_pending_articles(client, [_topic(1)], _articles(10), episode_id=7)

    assert len(seen_prompts) == 1
    assert stats.stored == 1
    assert stats.rejected == 1
    with judge_db.get_db_connection() as conn:
        log = conn.execute("SELECT phase, episode_id, status, model FROM llm_call_logs").fetchone()
    assert (log["phase"], log["episode_id"], log["status"], log["model"]) == ("topic_judge", 7, "success", "test-model")


def test_no_topics_or_articles_skips_llm(judge_db):
    client = FakeJudgeClient()

    assert judge_pending_articles(client, [], _articles(10)).pending == 0
    assert judge_pending_articles(client, [_topic(1)], []).pending == 0
    assert client.prompts == []


def test_judge_prompt_renders_with_contract_variables():
    text = render_prompt(
        "judge_topic_relevance",
        {"topics_json": "[]", "articles_json": "[]"},
    ).text

    assert '"relevance": {"1": 0, "2": 3}' in text
    assert "[]" in text
