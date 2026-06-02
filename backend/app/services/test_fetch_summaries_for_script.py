"""Test fetch_summaries_for_script with source filtering."""
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

