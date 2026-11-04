from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services import article_service as article_service_module
from app.services.article_service import ArticleService, without_topic_fields, write_fallback_summaries
from app.services.settings_service import (
    ProgramSettings,
    TopicSetting,
    topic_name_key,
    get_settings_or_default,
    topic_fingerprint,
    validate_settings,
)

JST_TODAY = datetime.now(article_service_module.JST).date().isoformat()


@pytest.fixture
def topic_db(monkeypatch, tmp_path):
    db_path = tmp_path / "selection.db"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    from app.db import connection
    monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    with connection.get_db_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    monkeypatch.delenv("SUMMARY_LOOKBACK_DAYS", raising=False)
    return connection


_next_id = iter(range(1000, 10000))


def _add_article(db, title, *, importance=3, category="society", summary="要約"):
    article_id = next(_next_id)
    with db.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO articles (id, title, source, url, summary, category, importance_score, status, published_at) "
            "VALUES (?, ?, 'src1', ?, ?, ?, ?, 'summarized', ?)",
            (article_id, title, f"https://example.com/{article_id}", summary, category, importance, JST_TODAY),
        )
    return article_id


def _topic(db, name, weight, *, description="", active=True):
    with db.get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO user_topics (name, name_key, description, weight, is_active) VALUES (?, ?, ?, ?, ?)",
            (name, topic_name_key(name), description, weight, int(active)),
        )
        topic_id = cursor.lastrowid
    return TopicSetting(topic_id, name, description, weight)


def _match(db, article_id, topic, relevance=3, fingerprint=None):
    with db.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO article_topic_matches (article_id, topic_id, relevance, fingerprint) VALUES (?, ?, ?, ?)",
            (article_id, topic.id, relevance,
             fingerprint or topic_fingerprint(topic.name, topic.description)),
        )


def _select(n, min_score, topics, **kwargs):
    return ArticleService().fetch_summaries_for_script(
        max_articles=n, min_importance_score=min_score, source="src1", topics=topics, **kwargs
    )


def _ids(rows):
    return [row["id"] for row in rows]


def test_without_topics_result_is_unchanged(topic_db):
    for index in range(8):
        _add_article(topic_db, f"記事{index}", importance=3 + index % 2, category="technology" if index < 4 else "business")
    baseline = _select(5, 3, None)
    assert _select(5, 3, []) == baseline
    assert all("topic_tier" not in row for row in baseline)


def test_normal_keeps_exactly_one_general_article_when_available(topic_db):
    # 1トピックの上限は3件のため、高比重は2トピックに分けて4件の枠を埋める。
    high = _topic(topic_db, "ローカルLLM", "high")
    other_high = _topic(topic_db, "推論基盤", "high")
    for index in range(2):
        _match(topic_db, _add_article(topic_db, f"LLM{index}", importance=3, category="technology"), high)
        _match(topic_db, _add_article(topic_db, f"推論{index}", importance=3, category="technology"), other_high)
    _add_article(topic_db, "経済の動き", importance=3, category="business")
    _add_article(topic_db, "スポーツ大会の結果", importance=3, category="sports")

    rows = _select(5, 3, [high, other_high])
    tiers = [row["topic_tier"] for row in rows]
    assert len(rows) == 5
    assert tiers.count("general") == 1
    assert tiers[:4] == ["high"] * 4


def test_high_topic_article_below_general_importance_is_still_selected_for_short(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    medium = _topic(topic_db, "量子化", "medium")
    high_id = _add_article(topic_db, "高比重の重要度2", importance=2, category="technology")
    _match(topic_db, high_id, high)
    medium_id = _add_article(topic_db, "中比重の重要度2", importance=2, category="technology")
    _match(topic_db, medium_id, medium)

    rows = _select(6, 4, [high, medium])
    assert high_id in _ids(rows)
    assert medium_id not in _ids(rows)


def test_topic_articles_bypass_category_cap_but_general_articles_do_not(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    for index in range(3):
        _match(topic_db, _add_article(topic_db, f"LLM{index}", importance=4, category="technology"), high)
    for index in range(3):
        _add_article(topic_db, f"一般技術{index}", importance=4, category="technology")

    rows = _select(6, 3, [high])
    topic_rows = [row for row in rows if row["topic_tier"] == "high"]
    general_rows = [row for row in rows if row["topic_tier"] == "general"]
    assert len(topic_rows) == 3
    assert len(general_rows) <= 2


def test_low_topic_is_limited_to_one_for_small_counts(topic_db):
    low = _topic(topic_db, "雑談", "low")
    for index in range(3):
        _match(topic_db, _add_article(topic_db, f"低{index}", importance=3, category=f"c{index}"), low)
    rows = _select(5, 3, [low])
    assert sum(1 for row in rows if row["topic_tier"] == "low") == 1


def test_leftover_topic_articles_fill_when_general_pool_is_short(topic_db):
    # 件数の補充では、トピック単位の上限を外して max_articles を満たす（低比重の上限は除く）。
    high = _topic(topic_db, "ローカルLLM", "high")
    for index in range(5):
        _match(topic_db, _add_article(topic_db, f"LLM{index}", importance=3, category=f"c{index}"), high)
    rows = _select(5, 3, [high])
    assert len(rows) == 5
    assert all(row["topic_tier"] == "high" for row in rows)


def test_similar_titles_keep_the_higher_tier_article(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    medium = _topic(topic_db, "量子化", "medium")
    high_id = _add_article(topic_db, "Ollama 0.5 がリリース", importance=3, category="technology")
    _match(topic_db, high_id, high)
    medium_id = _add_article(topic_db, "Ollama 0.5 リリース", importance=3, category="technology")
    _match(topic_db, medium_id, medium)

    rows = _select(5, 3, [high, medium])
    assert high_id in _ids(rows)
    assert medium_id not in _ids(rows)


def test_article_matching_high_and_low_is_treated_as_high(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    low = _topic(topic_db, "雑談", "low")
    article_id = _add_article(topic_db, "両方に一致", importance=3, category="technology")
    _match(topic_db, article_id, high, relevance=2)
    _match(topic_db, article_id, low, relevance=3)

    rows = {row["id"]: row for row in _select(5, 3, [high, low])}
    assert rows[article_id]["topic_tier"] == "high"
    assert {item["name"] for item in rows[article_id]["matched_topics"]} == {"ローカルLLM", "雑談"}


def test_stale_fingerprint_and_low_relevance_are_not_matches(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    stale_id = _add_article(topic_db, "古い判定", importance=3, category="technology")
    _match(topic_db, stale_id, high, fingerprint="0000000000000000")
    weak_id = _add_article(topic_db, "言及のみ", importance=3, category="business")
    _match(topic_db, weak_id, high, relevance=1)

    rows = {row["id"]: row for row in _select(5, 3, [high])}
    assert rows[stale_id]["topic_tier"] == "general"
    assert rows[weak_id]["topic_tier"] == "general"
    assert rows[stale_id]["matched_topics"] == []


def test_matched_article_outside_candidate_pool_is_added(topic_db, monkeypatch):
    monkeypatch.setattr(article_service_module, "_MAX_CANDIDATE_POOL_SIZE", 2)
    high = _topic(topic_db, "ローカルLLM", "high")
    for index in range(3):
        _add_article(topic_db, f"一般{index}", importance=5, category=f"c{index}")
    matched_id = _add_article(topic_db, "埋もれた関心記事", importance=2, category="sports")
    _match(topic_db, matched_id, high)

    rows = _select(5, 2, [high])
    assert matched_id in _ids(rows)


def test_weather_run_is_broken_in_final_order(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    for index in range(2):
        _match(topic_db, _add_article(topic_db, f"天気{index}台風", importance=3, category="weather"), high)
    _add_article(topic_db, "一般記事", importance=3, category="business")
    rows = _select(4, 3, [high])
    titles = [row["title"] for row in rows]
    for index in range(2, len(titles)):
        window = titles[index - 2:index + 1]
        assert not all("台風" in title for title in window)


def test_topic_fields_are_removed_from_llm_input_and_fallback_file(topic_db, tmp_path):
    high = _topic(topic_db, "ローカルLLM", "high")
    _match(topic_db, _add_article(topic_db, "LLM記事", importance=3, category="technology"), high)
    rows = _select(5, 3, [high])
    assert rows[0]["matched_topics"]

    stripped = without_topic_fields([dict(row) for row in rows])
    assert all("topic_tier" not in item and "matched_topics" not in item for item in stripped)

    output = tmp_path / "summaries.json"
    write_fallback_summaries(str(output), [dict(row) for row in rows])
    assert "matched_topics" not in output.read_text(encoding="utf-8")


def test_invalid_env_values_fall_back_to_defaults(topic_db, monkeypatch):
    monkeypatch.setenv("TOPIC_RELEVANCE_THRESHOLD", "9")
    monkeypatch.setenv("TOPIC_GENERAL_RESERVE_RATIO", "abc")
    monkeypatch.setenv("TOPIC_HIGH_MIN_IMPORTANCE", "")
    assert article_service_module._topic_relevance_threshold() == 2
    assert article_service_module._topic_general_reserve_ratio() == 0.2
    assert article_service_module._topic_high_min_importance() == 2


def test_round_half_up_for_general_reserve():
    assert article_service_module._round_half_up(2.5) == 3
    assert article_service_module._round_half_up(1.0) == 1


def test_topic_read_failure_keeps_saved_program_settings(topic_db):
    from app.db import connection
    from app.services import settings_service
    settings_service.save_settings(validate_settings(["technology"], [], "short"))
    with connection.get_db_connection() as conn:
        conn.execute("DROP TABLE user_topics")
    value = get_settings_or_default()
    assert value.priority_themes == ("technology",)
    assert value.duration_preset == "short"
    assert value.topics == ()


def test_saved_topics_flow_into_generation_params_and_applied_settings(topic_db):
    from app.services import settings_service
    _topic(topic_db, "ローカルLLM", "high", description="Ollama")
    _topic(topic_db, "無効", "low", active=False)
    value = get_settings_or_default()
    assert [topic.name for topic in value.topics] == ["ローカルLLM"]
    assert value.generation_params()["topics"] == list(value.topics)
    assert value.applied_dict()["topics"] == [{"name": "ローカルLLM", "weight": "high"}]
    assert "topics" not in value.to_dict()
    assert settings_service.validate_settings().topics == ()


def test_program_override_keeps_saved_topics():
    from types import SimpleNamespace

    from app.api.generate import _resolve_program_settings

    topic = TopicSetting(1, "ローカルLLM", "", "high")
    settings = ProgramSettings(topics=(topic,))
    profile = SimpleNamespace(
        priority_themes=None, excluded_themes=None, duration_preset=None,
        max_articles=None, min_importance_score=None,
    )
    resolved = _resolve_program_settings(profile, settings, None)
    assert resolved.topics == (topic,)


def _weather_run_ok(articles):
    flags = [article_service_module._is_weather_disaster_article(article) for article in articles]
    return not any(all(flags[index - 2:index + 1]) for index in range(2, len(flags)))


def test_enforce_weather_run_moves_earlier_normal_article_to_break_run():
    def weather(title):
        return {"id": title, "title": title, "category": "weather", "summary": "", "importance_score": 3}

    normal = {"id": "normal", "title": "一般記事", "category": "business", "summary": "", "importance_score": 3}
    articles = [weather("w1"), normal, weather("w2"), weather("w3"), weather("w4")]

    result = article_service_module._enforce_weather_run(articles)

    assert _weather_run_ok(result)
    assert sorted(article["id"] for article in result) == sorted(article["id"] for article in articles)


def test_enforce_weather_run_keeps_order_when_no_violation():
    articles = [
        {"id": 1, "title": "一般A", "category": "business", "summary": "", "importance_score": 3},
        {"id": 2, "title": "天気", "category": "weather", "summary": "", "importance_score": 3},
        {"id": 3, "title": "一般B", "category": "business", "summary": "", "importance_score": 3},
    ]
    assert article_service_module._enforce_weather_run(articles) == articles


def test_topic_tier_ties_are_ordered_by_newest_published_at(topic_db):
    high = _topic(topic_db, "ローカルLLM", "high")
    # 優先カテゴリの古い記事は SQL で先に並ぶため、ソートで新しい記事を前に出す必要がある。
    for title, category, published in (
        ("古い優先記事", "politics", (datetime.now(article_service_module.JST).date() - timedelta(days=2)).isoformat()),
        ("新しい記事", "society", JST_TODAY),
    ):
        with topic_db.get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO articles (title, source, url, summary, category, importance_score, status, published_at) "
                "VALUES (?, 'src1', ?, '要約', ?, 3, 'summarized', ?)",
                (title, f"https://example.com/{title}", category, published),
            )
            article_id = cursor.lastrowid
        _match(topic_db, article_id, high, relevance=3)
    rows = _select(5, 3, [high], priority_themes=["politics"])
    assert [row["title"] for row in rows] == ["新しい記事", "古い優先記事"]
