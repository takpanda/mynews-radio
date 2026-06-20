"""Tests for commentary generation pipeline."""

import json
from unittest.mock import patch, MagicMock

import pytest


class TestCommentaryGenerateRequestValidation:
    """Validate the POST /generate endpoint with url/style parameters."""

    def test_commentary_url_creates_episode_with_type_commentary(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "solo",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generating"
        assert "episode_id" in data

        # Verify episode type is commentary
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        episode = svc.get_episode(data["episode_id"])
        assert episode is not None
        assert episode["type"] == "commentary"
        assert episode["source_url"] == "https://example.com/article"

    def test_commentary_invalid_style_returns_400(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "invalid_style",
        })
        assert resp.status_code == 400

    def test_commentary_url_ignores_news_source(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "dialogue",
            "news_source": "yahoo_news",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generating"

    def test_radio_without_url_still_works(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-15",
            "enable_review": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data

        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        episode = svc.get_episode(data["episode_id"])
        assert episode is not None
        assert episode["type"] == "radio"


class TestRunCommentaryGeneration:
    """Test the _run_commentary_generation function with mocked dependencies."""

    def test_commentary_generation_success_path(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(
            date="2099-06-01",
            url="https://example.com/article",
            style="solo",
        )

        fake_script = '{"lines": [{"article_id": 1, "text": "This is a commentary"}]}'

        with patch("app.api.generate.fetch_article_by_url",
                   return_value={"title": "Test Article", "url": "https://example.com/article", "text": "Article body text here", "source": "url_input"}), \
             patch("app.api.generate.ArticleService.upsert_article", return_value=True), \
             patch("app.api.generate.ArticleService.fetch_new_articles", return_value=[]), \
             patch("app.api.generate.get_db_connection") as mock_conn, \
             patch("app.api.generate.generate_commentary_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1), \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: 123 if key == "id" else None
            mock_conn_instance = MagicMock()
            mock_conn_instance.__enter__.return_value.execute.return_value.fetchone.return_value = mock_row
            mock_conn.return_value = mock_conn_instance

            _run_commentary_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    def test_commentary_fails_on_fetch_error(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(
            date="2099-06-01",
            url="https://example.com/article",
            style="solo",
        )

        with patch("app.api.generate.fetch_article_by_url",
                   return_value={"title": "", "url": "https://example.com/article", "text": "", "source": "url_input"}):
            _run_commentary_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"

    def test_commentary_fails_on_script_generation_error(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(
            date="2099-06-01",
            url="https://example.com/article",
            style="solo",
        )

        with patch("app.api.generate.fetch_article_by_url",
                   return_value={"title": "Test", "url": "https://example.com/article", "text": "Body text here", "source": "url_input"}), \
             patch("app.api.generate.ArticleService.upsert_article", return_value=True), \
             patch("app.api.generate.ArticleService.fetch_new_articles", return_value=[]), \
             patch("app.api.generate.get_db_connection") as mock_conn, \
             patch("app.api.generate.generate_commentary_script", return_value=0):

            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: 123 if key == "id" else None
            mock_conn_instance = MagicMock()
            mock_conn_instance.__enter__.return_value.execute.return_value.fetchone.return_value = mock_row
            mock_conn.return_value = mock_conn_instance

            _run_commentary_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"

    def test_commentary_fails_on_synthesize_error(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(
            date="2099-06-01",
            url="https://example.com/article",
            style="solo",
        )

        with patch("app.api.generate.fetch_article_by_url",
                   return_value={"title": "Test", "url": "https://example.com/article", "text": "Body text here", "source": "url_input"}), \
             patch("app.api.generate.ArticleService.upsert_article", return_value=True), \
             patch("app.api.generate.ArticleService.fetch_new_articles", return_value=[]), \
             patch("app.api.generate.get_db_connection") as mock_conn, \
             patch("app.api.generate.generate_commentary_script", return_value=3), \
             patch("app.api.generate.synthesize_episode", side_effect=RuntimeError("tts error")):

            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: 123 if key == "id" else None
            mock_conn_instance = MagicMock()
            mock_conn_instance.__enter__.return_value.execute.return_value.fetchone.return_value = mock_row
            mock_conn.return_value = mock_conn_instance

            _run_commentary_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"


def _make_fake_open(script_json: str):
    """Return a mock `open` context manager that reads from a string."""
    def _open(*args, **kwargs):
        m = MagicMock()
        m.__enter__.return_value.read.return_value = script_json
        return m
    return _open
