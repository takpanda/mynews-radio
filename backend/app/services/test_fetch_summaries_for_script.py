"""Tests for fetch_summaries_for_script: source filtering and lookback days."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestFetchSummariesForScriptSourceFilter:
    @pytest.fixture
    def article_service(self):
        from app.services.article_service import ArticleService
        return ArticleService()

    @pytest.mark.parametrize("source", ["hatena_bookmark", "yahoo_news", "hatena_hotentry_all"])
    def test_source_filter_adds_condition_when_specified(self, article_service, source):
        with patch(
            "app.services.article_service.get_db_connection"
        ) as mock_conn:
            conn_instance = MagicMock()
            mock_conn.return_value.__enter__ = MagicMock(return_value=conn_instance)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            conn_instance.execute.return_value.fetchall.return_value = []

            article_service.fetch_summaries_for_script(
                max_articles=10, min_importance_score=3, source=source
            )

            call_args = conn_instance.execute.call_args[0]
            query = str(call_args[0]) if isinstance(call_args, tuple) else str(call_args.sql)
            assert f"AND source LIKE '%?%'" in str(query).replace("'", "") or "source = ?" in str(query)

    def test_no_source_filter_when_none(self, article_service):
        with patch(
            "app.services.article_service.get_db_connection"
        ) as mock_conn:
            conn_instance = MagicMock()
            mock_conn.return_value.__enter__ = MagicMock(return_value=conn_instance)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            conn_instance.execute.return_value.fetchall.return_value = []

            article_service.fetch_summaries_for_script(
                max_articles=10, min_importance_score=3, source=None
            )

            call_args = conn_instance.execute.call_args[0]
            query = str(call_args[0])
            assert "source =" not in query


class TestFetchSummariesForScriptRealDB:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        import sqlite3
        import os
        from unittest.mock import patch

        # Clear the cache of get_settings if possible to ensure our mock takes effect
        try:
            from app.config import get_settings
            if hasattr(get_settings, "cache_clear"):
                get_settings.cache_clear()
        except ImportError:
            pass

        with patch("app.db.connection.get_settings") as mock_settings:
            import tempfile
            # Use a temporary file to ensure all connection calls share the same DB instance
            db_fd, db_path = tempfile.mkstemp()
            os.close(db_fd)
            mock_settings.return_value.database_url = f"sqlite:///{db_path}"

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    source TEXT,
                    url TEXT,
                    text TEXT,
                    published_at TEXT,
                    status TEXT,
                    summary TEXT,
                    category TEXT,
                    importance_score INTEGER,
                    difficulty INTEGER
                )
            """)
            conn.commit()
            conn.close()

            yield db_path

            if os.path.exists(db_path):
                os.remove(db_path)

    @pytest.fixture
    def article_service(self):
        from app.services.article_service import ArticleService
        return ArticleService()

    def insert_mock_articles(self, conn, articles):
        cursor = conn.cursor()
        for a in articles:
            cursor.execute("""
                INSERT INTO articles (title, source, url, text, published_at, status, summary, category, importance_score, difficulty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (a['title'], a['source'], a['url'], a['text'], a['published_at'], a['status'], 
                  a['summary'], a['category'], a['importance_score'], a['difficulty']))
        conn.commit()

    def test_fetch_summaries_with_lookback(self, article_service, setup_db):
        from datetime import timezone as tz
        import os
        from datetime import datetime, timedelta
        
        jst = tz(timedelta(hours=9))
        today = datetime.now(jst).date()
        
        articles = [
            {"title": "Today", "source": "src1", "url": "u1", "text": "t1", 
             "published_at": (today).isoformat(), "status": "summarized", 
             "summary": "S1", "category": "C1", "importance_score": 5, "difficulty": 1},
            {"title": "2DaysAgo", "source": "src1", "url": "u2", "text": "t2", 
             "published_at": (today - timedelta(days=2)).isoformat(), "status": "summarized", 
             "summary": "S2", "category": "C1", "importance_score": 5, "difficulty": 1},
            {"title": "3DaysAgo", "source": "src1", "url": "u3", "text": "t3", 
             "published_at": (today - timedelta(days=3)).isoformat(), "status": "summarized", 
             "summary": "S3", "category": "C1", "importance_score": 5, "difficulty": 1},
            {"title": "4DaysAgo", "source": "src1", "url": "u4", "text": "t4", 
             "published_at": (today - timedelta(days=4)).isoformat(), "status": "summarized", 
             "summary": "S4", "category": "C1", "importance_score": 5, "difficulty": 1},
        ]
        
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            self.insert_mock_articles(conn, articles)
        
        # Test Lookback=3 (default if not set or 3)
        os.environ["SUMMARY_LOOKBACK_DAYS"] = "3"
        results = article_service.fetch_summaries_for_script(max_articles=10, min_importance_score=3, source="src1")
        assert len(results) == 3
        titles = [r['title'] for r in results]
        assert "Today" in titles
        assert "2DaysAgo" in titles
        assert "3DaysAgo" in titles
        assert "4DaysAgo" not in titles

        # Test Lookback=5
        os.environ["SUMMARY_LOOKBACK_DAYS"] = "5"
        results = article_service.fetch_summaries_for_script(max_articles=10, min_importance_score=3, source="src1")
        assert len(results) == 4
        titles = [r['title'] for r in results]
        assert "4DaysAgo" in titles

        # Test Lookback unset (defaults to 3 internally if not set or invalid)
        if "SUMMARY_LOOKBACK_DAYS" in os.environ:
            del os.environ["SUMMARY_LOOKBACK_DAYS"]
        results = article_service.fetch_summaries_for_script(max_articles=10, min_importance_score=3, source="src1")
        assert len(results) == 3
