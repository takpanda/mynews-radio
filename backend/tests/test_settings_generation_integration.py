from datetime import datetime, timezone

from app.services.article_service import ArticleService
from app.services.settings_service import validate_settings


def _insert_summary(conn, title, category, score):
    conn.execute(
        "INSERT INTO articles (title, source, url, text, summary, category, importance_score, "
        "difficulty, status, published_at) VALUES (?, ?, ?, '', ?, ?, ?, 1, 'summarized', ?)",
        (title, "test", f"https://example.test/{title}", title, category, score,
         datetime.now(timezone.utc).isoformat()),
    )


def test_saved_theme_contract_changes_selected_articles_and_preserves_safety_valve(monkeypatch):
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        _insert_summary(conn, "business", "business", 3)
        _insert_summary(conn, "sports", "sports", 3)
        _insert_summary(conn, "critical-technology", "technology", 5)
        _insert_summary(conn, "excluded-technology", "technology", 3)

    service = ArticleService()
    default = service.fetch_summaries_for_script(10, 2, source="test")
    assert {item["category"] for item in default} == {"business", "sports", "technology"}

    profile = validate_settings(["business"], ["sports", "technology"], "normal")
    selected = service.fetch_summaries_for_script(
        **profile.generation_params(), source="test"
    )
    assert selected[0]["category"] == "business"
    assert "sports" not in {item["category"] for item in selected}
    assert "critical-technology" in {item["title"] for item in selected}
    assert "excluded-technology" not in {item["title"] for item in selected}
