from datetime import datetime, timezone

from app.services.article_service import (
    ArticleService,
    _is_weather_disaster_article,
    _prioritize_high_impact_articles,
    normalize_title,
    titles_are_similar,
)


def _insert_summary(title: str, score: int) -> None:
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                title, source, url, text, summary, category, importance_score,
                difficulty, status, published_at
            ) VALUES (?, ?, ?, '', ?, 'technology', ?, 1, 'summarized', ?)
            """,
            (
                title,
                "test",
                f"https://example.test/{score}-{title}",
                title,
                score,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def _insert_summary_with_category(title: str, category: str, score: int) -> None:
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                title, source, url, text, summary, category, importance_score,
                difficulty, status, published_at
            ) VALUES (?, ?, ?, '', ?, ?, ?, 1, 'summarized', ?)
            """,
            (
                title,
                "test",
                f"https://example.test/{score}-{title}",
                title,
                category,
                score,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def test_normalize_title_handles_width_accents_and_punctuation():
    assert normalize_title(" ＯｐｅｎＡＩ：「Jalapeño」！？ ") == "openaijalapeno"
    assert normalize_title("OpenAI：「ハラペーニョ」") == "openaiハラペーニョ"


def test_transliterated_titles_are_similar_but_distinct_events_are_not():
    assert titles_are_similar("OpenAI、ハラペーニョを発表", "OpenAI announces Jalapeño")
    assert titles_are_similar("OpenAIのハラペーニョを発表", "OpenAI announces Jalapeño")
    assert not titles_are_similar("OpenAI、Jalapeñoを発表", "OpenAI、Jalapeñoの料理レシピ")
    assert not titles_are_similar("OpenAI、新機能を発表", "OpenAI、別機能を発表")
    assert not titles_are_similar("OpenAIのセキュリティ対応", "OpenAI enterprise security review")


def test_fetch_summaries_removes_later_transliterated_duplicate_and_keeps_order():
    from app.services.article_service import ArticleService

    _insert_summary("OpenAI、ハラペーニョを発表", score=5)
    _insert_summary("OpenAI announces Jalapeño", score=4)
    _insert_summary("米国市場で株価が上昇", score=3)

    summaries = ArticleService().fetch_summaries_for_script(
        max_articles=10,
        min_importance_score=3,
        source="test",
    )

    assert [summary["title"] for summary in summaries] == [
        "OpenAI、ハラペーニョを発表",
        "米国市場で株価が上昇",
    ]


def test_fetch_summaries_limits_known_topic_to_two_and_fills_with_later_candidates():
    for index in range(3):
        _insert_summary_with_category(f"テクノロジー記事{index}", "technology", 5)
    _insert_summary_with_category("社会記事", "society", 4)
    _insert_summary_with_category("企業の決算発表", "business", 4)

    summaries = ArticleService().fetch_summaries_for_script(
        max_articles=4,
        min_importance_score=3,
        source="test",
    )

    assert len(summaries) == 4
    assert sum(item["category"] == "technology" for item in summaries) == 2
    assert sum(item["category"] == "society" for item in summaries) == 1
    assert sum(item["category"] == "business" for item in summaries) == 1


def test_weather_detection_does_not_use_single_character_substrings():
    assert not _is_weather_disaster_article({"title": "雨宮さんの新作", "summary": ""})
    assert not _is_weather_disaster_article({"title": "雪村選手が会見", "summary": ""})
    assert not _is_weather_disaster_article({"title": "雷門でイベント", "summary": ""})
    assert _is_weather_disaster_article({"title": "大雨による避難", "summary": ""})


def test_fetch_summaries_breaks_weather_disaster_run_when_alternative_exists():
    for index in range(3):
        _insert_summary_with_category(f"大雨に関する記事{index}", "society", 5)
    _insert_summary_with_category("企業の決算発表", "business", 4)

    summaries = ArticleService().fetch_summaries_for_script(
        max_articles=4,
        min_importance_score=3,
        source="test",
    )

    assert len(summaries) == 4
    assert summaries[2]["title"] == "企業の決算発表"
    assert {item["title"] for item in summaries} == {
        "大雨に関する記事0",
        "大雨に関する記事1",
        "大雨に関する記事2",
        "企業の決算発表",
    }
    assert not any(
        all("大雨" in item["title"] for item in summaries[index:index + 3])
        for index in range(len(summaries) - 2)
    )


def test_prioritizes_high_impact_priority_theme_after_filtering():
    filtered = [
        {"title": "天気情報", "category": "society", "importance_score": 5},
        {"title": "安全保障の動き", "category": "business", "importance_score": 4},
        {"title": "企業ニュース", "category": "business", "importance_score": 3},
    ]

    reordered = _prioritize_high_impact_articles(filtered, ["business"])

    assert [article["title"] for article in reordered] == [
        "安全保障の動き",
        "天気情報",
        "企業ニュース",
    ]


def test_priority_theme_below_high_impact_threshold_keeps_existing_order():
    filtered = [
        {"title": "重要度5の一般記事", "category": "general", "importance_score": 5},
        {"title": "優先テーマだが重要度3", "category": "business", "importance_score": 3},
    ]

    reordered = _prioritize_high_impact_articles(filtered, ["business"])

    assert reordered == filtered


def test_priority_theme_absent_keeps_existing_order_as_fallback():
    filtered = [
        {"title": "一般記事", "category": "general", "importance_score": 5},
        {"title": "企業ニュース", "category": "business", "importance_score": 4},
    ]

    reordered = _prioritize_high_impact_articles(filtered, ["sports"])

    assert reordered == filtered


def test_prioritization_preserves_weather_disaster_run_limit():
    filtered = [
        {"title": "大雨1", "category": "society", "summary": "大雨", "importance_score": 5},
        {"title": "大雨2", "category": "society", "summary": "大雨", "importance_score": 5},
        {"title": "大雨3", "category": "society", "summary": "大雨", "importance_score": 4},
        {"title": "一般記事", "category": "business", "summary": "企業", "importance_score": 3},
    ]

    reordered = _prioritize_high_impact_articles(filtered, ["society"])

    assert [article["title"] for article in reordered] == [
        "大雨1",
        "大雨2",
        "一般記事",
        "大雨3",
    ]
    assert not any(
        all(_is_weather_disaster_article(item) for item in reordered[index:index + 3])
        for index in range(len(reordered) - 2)
    )
