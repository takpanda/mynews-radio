import os
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
        source: str | None = None,
        priority_themes: list[str] | tuple[str, ...] | None = None,
        excluded_themes: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        _raw_lookback = os.getenv("SUMMARY_LOOKBACK_DAYS")
        try:
            lookback_days = int(_raw_lookback) if _raw_lookback else 3
            if lookback_days < 1:
                lookback_days = 3
        except (ValueError, TypeError):
            lookback_days = 3
        since_date = (datetime.now(JST).date() - timedelta(days=lookback_days)).isoformat()
        priority = list(priority_themes or [])
        excluded = list(excluded_themes or [])
        where = [
            "status = 'summarized'",
            "summary IS NOT NULL",
            "summary != ''",
            "importance_score >= ?",
            "published_at >= ?",
        ]
        params: list[Any] = [min_importance_score, since_date]
        if source is not None:
            where.append("source = ?")
            params.append(source)
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            # Safety valve B: critical technology/society news remains eligible.
            where.append(
                f"(category NOT IN ({placeholders}) OR "
                "(importance_score >= 5 AND category IN ('technology', 'society')) OR category IS NULL)"
            )
            params.extend(excluded)
        order = "importance_score DESC, published_at DESC, id DESC"
        if priority:
            placeholders = ",".join("?" for _ in priority)
            order = f"CASE WHEN category IN ({placeholders}) THEN 0 ELSE 1 END, {order}"
            params.extend(priority)
        params.append(max_articles)
        query = (
            "SELECT id, title, source, url, summary, category, importance_score, difficulty "
            f"FROM articles WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
        )
        with get_db_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def fetch_and_store_article_by_url(self, url: str, timeout: int = 10) -> bool:
        """Fetch article from URL and store in DB with source='url_commentary'.

        Args:
            url: HTTP(S) URL of the article to fetch.
            timeout: Request timeout in seconds.

        Returns:
            True if inserted, False if duplicate (url UNIQUE constraint).

        Raises:
            ValueError: Invalid URL.
            urllib.error.URLError: Network error.
            RuntimeError: Extraction failure.
        """
        from app.services.url_fetcher import fetch_article_by_url

        article = fetch_article_by_url(url, timeout=timeout)
        return self.upsert_article(article)

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
