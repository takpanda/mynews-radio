"""Tests for url_fetcher module."""
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

# trafilatura is not installed in the test env. Pre-populate sys.modules
# so the lazy import inside url_fetcher resolves to a mock module.
_MOCK_TRAFILATURA = MagicMock()
_MOCK_TRAFILATURA.extract = MagicMock()
sys.modules["trafilatura"] = _MOCK_TRAFILATURA

from app.services.url_fetcher import fetch_article_by_url
from app.services.article_service import ArticleService

_VALID_URL = "https://example.com/article"


def _make_resp_headers(charset: str = "utf-8") -> MagicMock:
    h = MagicMock()
    h.get_content_charset.return_value = charset
    return h


def _mock_resp(data: bytes = b"<html>ok</html>", charset: str = "utf-8") -> MagicMock:
    m = MagicMock()
    m.read.return_value = data
    m.headers = _make_resp_headers(charset)
    return m


@pytest.fixture(autouse=True)
def _reset_trafilatura_mock():
    """Reset the shared trafilatura mock before each test so side_effect
    and return_value from an earlier test do not bleed into the next one."""
    _MOCK_TRAFILATURA.extract.reset_mock(return_value=True, side_effect=True)
    yield


class TestFetchArticleByUrl:

    def test_successful_fetch(self):
        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "A" * 60 + " article body long enough for the fifty character check.",
            "title": "Test Article",
            "date": "2026-06-20T12:34:56",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            result = fetch_article_by_url(_VALID_URL)

        assert result["title"] == "Test Article"
        assert result["url"] == _VALID_URL
        assert result["source"] == "url_commentary"
        assert result["published_at"] == "2026-06-20"
        assert len(result["text"]) >= 50

    def test_missing_title_uses_fallback(self):
        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "B" * 60 + " enough body text to pass the minimum length requirement here.",
            "title": "",
            "date": "",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            result = fetch_article_by_url(_VALID_URL)

        assert result["title"] == f"Article from {_VALID_URL}"
        assert result["published_at"] is not None

    def test_missing_date_falls_back_to_jst_today(self):
        from datetime import datetime, timezone, timedelta

        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "C" * 60 + " body text that is long enough to satisfy minimum requirement.",
            "title": "No Date",
            "date": None,
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            result = fetch_article_by_url(_VALID_URL)

        JST = timezone(timedelta(hours=9))
        expected = datetime.now(JST).date().isoformat()
        assert result["published_at"] == expected

    @pytest.mark.parametrize("bad_url", [
        "",
        "not-a-url",
        "ftp://example.com/file",
        "file:///tmp/doc.txt",
    ])
    def test_invalid_url_raises_value_error(self, bad_url):
        with pytest.raises(ValueError, match="Invalid URL"):
            fetch_article_by_url(bad_url)

    def test_network_error_raised(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("host unreachable")):
            with pytest.raises(urllib.error.URLError):
                fetch_article_by_url(_VALID_URL)

    def test_http_error_raised(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(_VALID_URL, 404, "Not Found", {}, None),
        ):
            with pytest.raises(urllib.error.HTTPError):
                fetch_article_by_url(_VALID_URL)

    def test_trafilatura_returns_none(self):
        _MOCK_TRAFILATURA.extract.return_value = None

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            with pytest.raises(RuntimeError, match="Could not extract article content"):
                fetch_article_by_url(_VALID_URL)

    def test_insufficient_content_raises(self):
        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "Short",
            "title": "Too short",
            "date": "",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            with pytest.raises(RuntimeError, match="Insufficient article content"):
                fetch_article_by_url(_VALID_URL)

    def test_empty_text_raises(self):
        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "",
            "title": "Empty text",
            "date": "",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            with pytest.raises(RuntimeError, match="Insufficient article content"):
                fetch_article_by_url(_VALID_URL)

    def test_trafilatura_exception_wrapped(self):
        _MOCK_TRAFILATURA.extract.side_effect = ValueError("bad extraction")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            with pytest.raises(RuntimeError, match="Failed to extract article"):
                fetch_article_by_url(_VALID_URL)

    def test_timeout_passed_to_urlopen(self):
        _MOCK_TRAFILATURA.extract.return_value = {
            "text": "D" * 60 + " body with enough content to pass the minimum fifty character threshold.",
            "title": "Timeout Test",
            "date": "",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = _mock_resp()
            fetch_article_by_url(_VALID_URL, timeout=5)

        _call_kwargs = mock_urlopen.call_args[1]
        assert _call_kwargs.get("timeout") == 5


class TestFetchAndStoreArticleByUrl:

    @patch("app.services.url_fetcher.fetch_article_by_url")
    def test_successful_store(self, mock_fetch):
        mock_fetch.return_value = {
            "title": "Stored",
            "url": _VALID_URL,
            "text": "E" * 60 + " body text that is long enough to satisfy the minimum fifty characters.",
            "source": "url_commentary",
            "published_at": "2026-06-20",
        }

        svc = ArticleService()
        result = svc.fetch_and_store_article_by_url(_VALID_URL)

        assert result is True

    @patch("app.services.url_fetcher.fetch_article_by_url")
    def test_duplicate_url_returns_false(self, mock_fetch):
        mock_fetch.return_value = {
            "title": "Dup",
            "url": _VALID_URL,
            "text": "F" * 60 + " body text that meets the minimum fifty character requirement here.",
            "source": "url_commentary",
            "published_at": "2026-06-20",
        }

        svc = ArticleService()
        svc.fetch_and_store_article_by_url(_VALID_URL)
        result = svc.fetch_and_store_article_by_url(_VALID_URL)

        assert result is False
