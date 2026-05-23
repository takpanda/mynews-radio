from typing import Any

from app.db.connection import get_db_connection


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
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE articles
                SET summary = ?,
                    category = ?,
                    importance_score = ?,
                    status = ?
                WHERE id = ?
                """,
                (summary, category, importance_score, status, article_id),
            )

    def fetch_summaries_for_script(
        self,
        max_articles: int,
        min_importance_score: int,
    ) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source, url, summary, category, importance_score
                FROM articles
                WHERE status = 'summarized'
                  AND summary IS NOT NULL
                  AND importance_score >= ?
                ORDER BY importance_score DESC, published_at DESC, id ASC
                LIMIT ?
                """,
                (min_importance_score, max_articles),
            ).fetchall()
            return [dict(row) for row in rows]
