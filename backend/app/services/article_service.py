from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.connection import get_db_connection


JST = timezone(timedelta(hours=9))


class ArticleService:
    def upsert_article(self, article: dict[str, Any]) -> bool:
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO articles (
                    title, source, url, text, published_at, status
                ) VALUES (?, ?, ?, ?, ?, 'new')
                """,
                (
                    article.get("title", ""),
                    article.get("source"),
                    article.get("url"),
                    article.get("text", ""),
                    article.get("published_at"),
                ),
            )
            return cursor.rowcount > 0

    def fetch_new_articles(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source, url, text, published_at
                FROM articles
                WHERE status = 'new'
                ORDER BY published_at DESC, id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def update_summary(
        self,
        article_id: int,
        summary: str,
        category: str,
        importance_score: int,
        status: str,
        difficulty: int = 1,
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE articles
                SET summary = ?,
                    category = ?,
                    importance_score = ?,
                    difficulty = ?,
                    status = ?
                WHERE id = ?
                """,
                (summary, category, importance_score, difficulty, status, article_id),
            )

    def fetch_summaries_for_script(
        self,
        max_articles: int,
        min_importance_score: int,
    ) -> list[dict[str, Any]]:
        today_jst = datetime.now(JST).date().isoformat()
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source, url, summary, category, importance_score, difficulty
                FROM articles
                WHERE status = 'summarized'
                  AND summary IS NOT NULL
                  AND summary != ''
                  AND importance_score >= ?
                  AND published_at = ?
                ORDER BY importance_score DESC, published_at DESC, id DESC
                LIMIT ?
                """,
                (min_importance_score, today_jst, max_articles),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_articles_used(self, article_ids: list[int]) -> None:
        """Mark articles as 'used' so they are not reused in future episode scripts."""
        if not article_ids:
            return
        placeholders = ",".join("?" * len(article_ids))
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE articles SET status = 'used' WHERE id IN ({placeholders}) AND status = 'summarized'",
                article_ids,
            )
