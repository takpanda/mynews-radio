from datetime import datetime, timezone

from app.services.article_service import normalize_title, titles_are_similar


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
