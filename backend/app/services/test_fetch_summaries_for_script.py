"""Test fetch_summaries_for_script with source filtering."""
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


class TestFetchSummariesForScriptLookbackDays:
    @pytest.fixture(autouse=True)
    def _clean_env(self):
        import os as real_os
        original = real_os.environ.get("SUMMARY_LOOKBACK_DAYS")
        if "SUMMARY_LOOKBACK_DAYS" in real_os.environ:
            del real_os.environ["SUMMARY_LOOKBACK_DAYS"]
        yield
        if original is not None:
            real_os.environ["SUMMARY_LOOKBACK_DAYS"] = original

    @pytest.fixture
    def article_service(self):
        from app.services.article_service import ArticleService
        return ArticleService()

    def _mock_conn(self, mock_conn):
        conn_instance = MagicMock()
        mock_conn.return_value.__enter__ = MagicMock(return_value=conn_instance)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        conn_instance.execute.return_value.fetchall.return_value = []
        return conn_instance

    def test_default_lookback_days_is_3(self, article_service):
        from datetime import timezone, timedelta as td
        jst = timezone(td(hours=9))
        expected_since = (datetime.now(jst).date() - timedelta(days=3)).isoformat()

        with patch("app.services.article_service.get_db_connection") as mock_conn:
            conn_instance = self._mock_conn(mock_conn)

            article_service.fetch_summaries_for_script(
                max_articles=10, min_importance_score=3, source=None
            )

            query_call_args = conn_instance.execute.call_args[0]
            params = query_call_args[1] if len(query_call_args) > 1 else ()
            assert expected_since in [str(p) for p in params], (
                f"Expected {expected_since} in params: {[str(p) for p in params]}"
            )

    def test_custom_lookback_days(self, article_service):
        from datetime import timezone, timedelta as td
        jst = timezone(td(hours=9))
        expected_since = (datetime.now(jst).date() - timedelta(days=7)).isoformat()

        with patch("app.services.article_service.get_db_connection") as mock_conn:
            conn_instance = self._mock_conn(mock_conn)
            with patch.dict("os.environ", {"SUMMARY_LOOKBACK_DAYS": "7"}):
                article_service.fetch_summaries_for_script(
                    max_articles=10, min_importance_score=3, source=None
                )

            query_call_args = conn_instance.execute.call_args[0]
            params = query_call_args[1] if len(query_call_args) > 1 else ()
            assert expected_since in [str(p) for p in params], (
                f"Expected {expected_since} in params: {[str(p) for p in params]}"
            )

    def test_uses_greater_equal_instead_of_equality(self, article_service):
        with patch("app.services.article_service.get_db_connection") as mock_conn:
            conn_instance = self._mock_conn(mock_conn)

            article_service.fetch_summaries_for_script(
                max_articles=10, min_importance_score=3, source=None
            )

            query_call_args = conn_instance.execute.call_args[0]
            sql = str(query_call_args[0]) if len(query_call_args) > 0 else ""
            assert "published_at >=" in sql, (
                f"SQL should use 'published_at >=' instead of '=': {sql}"
            )

    def test_lookback_with_source_filter(self, article_service):
        from datetime import timezone, timedelta as td
        jst = timezone(td(hours=9))
        expected_since = (datetime.now(jst).date() - timedelta(days=5)).isoformat()

        with patch("app.services.article_service.get_db_connection") as mock_conn:
            conn_instance = self._mock_conn(mock_conn)
            with patch.dict("os.environ", {"SUMMARY_LOOKBACK_DAYS": "5"}):
                article_service.fetch_summaries_for_script(
                    max_articles=10, min_importance_score=3, source="hatena_bookmark"
                )

            query_call_args = conn_instance.execute.call_args[0]
            sql = str(query_call_args[0]) if len(query_call_args) > 0 else ""
            params = query_call_args[1] if len(query_call_args) > 1 else ()

            assert "published_at >=" in sql, (
                f"SQL should use 'published_at '>=': {sql}"
            )
            assert expected_since in [str(p) for p in params], (
                f"Expected {expected_since} in params: {[str(p) for p in params]}"
            )

    def test_sort_order_preserved(self, article_service):
        with patch("app.services.article_service.get_db_connection") as mock_conn:
            conn_instance = self._mock_conn(mock_conn)

            article_service.fetch_summaries_for_script(
                max_articles=10, min_importance_score=3, source=None
            )

            query_call_args = conn_instance.execute.call_args[0]
            sql = str(query_call_args[0]) if len(query_call_args) > 0 else ""
            assert "ORDER BY importance_score DESC" in sql, (
                f"Sort order must be preserved: {sql}"
            )
            assert "published_at DESC" in sql, (
                f"Sort order must include published_at DESC: {sql}"
            )

 

