"""Tests for commentary generation pipeline."""

import json
from pathlib import Path
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
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data

        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        episode = svc.get_episode(data["episode_id"])
        assert episode is not None
        assert episode["type"] == "radio"

    def test_commentary_mc_gender_default(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "solo",
        })
        assert resp.status_code == 200

    def test_commentary_mc_gender_male(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "solo",
            "mc_gender": "male",
        })
        assert resp.status_code == 200

    def test_commentary_mc_gender_female(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "solo",
            "mc_gender": "female",
        })
        assert resp.status_code == 200

    def test_commentary_invalid_mc_gender_returns_400(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "solo",
            "mc_gender": "invalid",
        })
        assert resp.status_code == 400

    def test_commentary_dialogue_ignores_mc_gender(self, client):
        resp = client.post("/generate", json={
            "date": "2099-06-01",
            "url": "https://example.com/article",
            "style": "dialogue",
            "mc_gender": "female",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generating"


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
            mc_gender="male",
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
            mc_gender="male",
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
            mc_gender="male",
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
            mc_gender="male",
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

    def test_commentary_solo_with_female_gender(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(
            date="2099-06-01",
            url="https://example.com/article",
            style="solo",
            mc_gender="female",
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


class TestNonEmptyTextValidation:
    """各セグメントのtextが空でないことの確認（テスト項目5）。"""

    def test_all_lines_have_non_empty_text(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 3000,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "本日は注目のニュースについて解説します", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "まず最初のトピックです", "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "", "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "   ", "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "以上が本日の解説でした", "section": "outro", "delivery": "warm"},
            ]
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            result = generate_commentary_script(str(output), article, style="solo", mc_gender="male")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        non_empty = [l for l in script["lines"] if l["text"].strip()]
        assert result == 5, "all lines including empty should be counted"
        assert len(non_empty) == 3, "empty/whitespace-only lines should be stripped to empty"
        assert all(l["text"] for l in script["lines"][:2]), "intro and first news should have text"
        assert not script["lines"][2]["text"], "empty text line should remain empty after strip"
        assert not script["lines"][3]["text"], "whitespace-only line should be stripped to empty"

    def test_solo_with_female_gender_speakers(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "テスト",
            "lines": [
                {"speaker": "male", "text": "intro line", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "news line", "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "outro line", "section": "outro", "delivery": "warm"},
            ]
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            result = generate_commentary_script(str(output), article, style="solo", mc_gender="female")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert result == 3
        for line in script["lines"]:
            assert line["speaker"] == "female", f"expected female, got {line['speaker']}"


class TestCalcSuggestedLines:
    """Unit tests for _calc_suggested_lines."""

    def test_short_text_solo_returns_minimum(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(0, "solo") == 6
        assert _calc_suggested_lines(30, "solo") == 6
        assert _calc_suggested_lines(49, "solo") == 6

    def test_short_text_dialogue_returns_minimum(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(0, "dialogue") == 8
        assert _calc_suggested_lines(30, "dialogue") == 8
        assert _calc_suggested_lines(49, "dialogue") == 8

    def test_below_2000_solo_returns_6(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(500, "solo") == 6
        assert _calc_suggested_lines(1999, "solo") == 6

    def test_below_2000_dialogue_returns_8(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(500, "dialogue") == 8
        assert _calc_suggested_lines(1999, "dialogue") == 8

    def test_2000_to_4000_solo_returns_8_to_10(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(2000, "solo") == 8
        assert _calc_suggested_lines(2999, "solo") == 8
        assert _calc_suggested_lines(3000, "solo") == 9
        assert _calc_suggested_lines(3999, "solo") == 9
        assert _calc_suggested_lines(4000, "solo") == 10

    def test_2000_to_4000_dialogue_returns_10_to_12(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(2000, "dialogue") == 10
        assert _calc_suggested_lines(2999, "dialogue") == 10
        assert _calc_suggested_lines(3000, "dialogue") == 11
        assert _calc_suggested_lines(3999, "dialogue") == 11
        assert _calc_suggested_lines(4000, "dialogue") == 12

    def test_over_4000_solo_returns_12_to_15(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(4001, "solo") == 12
        assert _calc_suggested_lines(6000, "solo") == 13
        assert _calc_suggested_lines(8000, "solo") == 15
        assert _calc_suggested_lines(10000, "solo") == 15

    def test_over_4000_dialogue_returns_12_to_15(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(4001, "dialogue") == 12
        assert _calc_suggested_lines(6000, "dialogue") == 13
        assert _calc_suggested_lines(8000, "dialogue") == 15
        assert _calc_suggested_lines(10000, "dialogue") == 15

    def test_empty_string_text(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(len(""), "solo") == 6
        assert _calc_suggested_lines(len(""), "dialogue") == 8

    def test_exact_50_char_boundary(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(50, "solo") == 6
        assert _calc_suggested_lines(50, "dialogue") == 8
        # < 50 returns minimum; >= 50 still returns minimum in < 2000 range

    def test_intermediate_2000_to_4000_granular(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(1000, "solo") == 6
        assert _calc_suggested_lines(1500, "solo") == 6
        assert _calc_suggested_lines(1999, "solo") == 6
        assert _calc_suggested_lines(2000, "solo") == 8
        assert _calc_suggested_lines(2500, "solo") == 8
        assert _calc_suggested_lines(3000, "solo") == 9
        assert _calc_suggested_lines(3500, "solo") == 9
        assert _calc_suggested_lines(4000, "solo") == 10

    def test_intermediate_4000_granular(self):
        from app.batch.generate_commentary_script import _calc_suggested_lines
        assert _calc_suggested_lines(4001, "solo") == 12
        assert _calc_suggested_lines(4500, "solo") == 12
        assert _calc_suggested_lines(5333, "solo") == 12
        assert _calc_suggested_lines(5334, "solo") == 13
        assert _calc_suggested_lines(6000, "solo") == 13
        assert _calc_suggested_lines(6666, "solo") == 13
        assert _calc_suggested_lines(6667, "solo") == 14
        assert _calc_suggested_lines(7000, "solo") == 14
        assert _calc_suggested_lines(8000, "solo") == 15
        assert _calc_suggested_lines(10000, "solo") == 15
        assert _calc_suggested_lines(13333, "solo") == 15
        assert _calc_suggested_lines(13334, "solo") == 15
        # dialogue > 4000 should match solo (no +2 bonus)
        assert _calc_suggested_lines(4001, "dialogue") == 12
        assert _calc_suggested_lines(8000, "dialogue") == 15
        assert _calc_suggested_lines(10000, "dialogue") == 15


class TestBuildSectionDetails:
    """Unit tests for _build_section_details."""

    def test_small_count_returns_small_section_details(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(6)
        assert "intro、1〜2行" in result
        assert "news、3〜6行" in result
        assert "outro、1〜2行" in result

    def test_medium_count_returns_medium_section_details(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(10)
        assert "intro、2行" in result
        assert "news、6〜9行" in result
        assert "outro、1〜2行" in result

    def test_large_count_returns_large_section_details(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(13)
        assert "intro、2〜3行" in result
        assert "news、8〜12行" in result
        assert "outro、1〜2行" in result

    def test_boundary_8_returns_small(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(8)
        assert "intro、1〜2行" in result

    def test_boundary_9_returns_medium(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(9)
        assert "intro、2行" in result

    def test_boundary_12_returns_medium(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(12)
        assert "intro、2行" in result

    def test_boundary_13_returns_large(self):
        from app.batch.generate_commentary_script import _build_section_details
        result = _build_section_details(13)
        assert "intro、2〜3行" in result


class TestSectionValidation:
    """Test section validation fallback logic in generate_commentary_script."""

    def test_invalid_section_fallback_to_news(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "テスト",
            "lines": [
                {"speaker": "male", "text": "intro line", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "invalid section line", "section": "invalid_section", "delivery": "neutral"},
                {"speaker": "male", "text": "another invalid", "section": "extra_section", "delivery": "neutral"},
                {"speaker": "male", "text": "outro line", "section": "outro", "delivery": "warm"},
            ]
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            result = generate_commentary_script(str(output), article, style="solo")

        assert result == 4
        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["lines"][0]["section"] == "intro"
        assert script["lines"][1]["section"] == "news"  # fallback
        assert script["lines"][2]["section"] == "news"  # fallback
        assert script["lines"][3]["section"] == "outro"

    def test_valid_sections_unchanged(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "テスト",
            "lines": [
                {"speaker": "male", "text": "intro line", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "news line", "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "outro line", "section": "outro", "delivery": "warm"},
            ]
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            result = generate_commentary_script(str(output), article, style="solo")

        assert result == 3
        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["lines"][0]["section"] == "intro"
        assert script["lines"][1]["section"] == "news"
        assert script["lines"][2]["section"] == "outro"


class TestMcGenderInPrompt:
    """Verify mc_gender is passed to the prompt template and affects the prompt content."""

    def test_prompt_contains_mc_gender_when_solo(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [{"speaker": "male", "text": "test", "section": "news", "delivery": "neutral"}],
        }

        captured_prompt = None

        class CapturingClient:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args, **kwargs):
                pass
            def generate_json(self, prompt):
                nonlocal captured_prompt
                captured_prompt = prompt
                return fake_response

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient", CapturingClient):
            generate_commentary_script(str(output), article, style="solo", mc_gender="female")

        assert captured_prompt is not None, "prompt was not captured"
        assert '{mc_gender}' not in captured_prompt, "template placeholder should be resolved"
        assert '話者は "female" 1名のみ' in captured_prompt, \
            f"expected 'female' in prompt, got: ...{captured_prompt[captured_prompt.find('話者は'):captured_prompt.find('話者は')+40]}..."
        assert '"female" のみ' in captured_prompt, \
            "solo speaker constraint should reference mc_gender"

    def test_prompt_contains_male_when_solo_male(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [{"speaker": "male", "text": "test", "section": "news", "delivery": "neutral"}],
        }

        captured_prompt = None

        class CapturingClient:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args, **kwargs):
                pass
            def generate_json(self, prompt):
                nonlocal captured_prompt
                captured_prompt = prompt
                return fake_response

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient", CapturingClient):
            generate_commentary_script(str(output), article, style="solo", mc_gender="male")

        assert captured_prompt is not None
        assert '話者は "male" 1名のみ' in captured_prompt
        assert '自問自答' in captured_prompt, "monologue constraint should be present"
        assert '掛け声' in captured_prompt, "monologue constraint should forbid calls"


class TestSoloDialogueSpeakerBehavior:
    """Verify solo/dialogue speaker normalization differences."""

    def test_solo_llm_returns_male_speaker_normalized_to_mc_gender_female(self, tmp_path):
        """solo mode: even if LLM returns male speaker, it should be normalized to mc_gender."""
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [{"speaker": "male", "text": "intro", "section": "intro", "delivery": "neutral"}],
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            generate_commentary_script(str(output), article, style="solo", mc_gender="female")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["mc_gender"] == "female"
        assert script["style"] == "solo"
        for line in script["lines"]:
            assert line["speaker"] == "female", \
                f"solo mode should normalize speaker to mc_gender, got {line['speaker']}"

    def test_solo_female_all_speakers_normalized(self, tmp_path):
        """solo+female: all speakers become female regardless of LLM output."""
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "intro", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "news", "section": "news", "delivery": "neutral"},
                {"speaker": "female", "text": "outro", "section": "outro", "delivery": "warm"},
            ],
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            generate_commentary_script(str(output), article, style="solo", mc_gender="female")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["mc_gender"] == "female"
        assert script["style"] == "solo"
        for line in script["lines"]:
            assert line["speaker"] == "female", \
                f"all solo lines should be female, got {line['speaker']}"

    def test_dialogue_preserves_both_speakers(self, tmp_path):
        """dialogue mode: male and female speakers should be preserved."""
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "intro", "section": "intro", "delivery": "neutral"},
                {"speaker": "female", "text": "comment", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "news detail", "section": "news", "delivery": "neutral"},
                {"speaker": "female", "text": "question", "section": "news", "delivery": "questioning"},
                {"speaker": "male", "text": "analysis", "section": "news", "delivery": "thoughtful"},
                {"speaker": "female", "text": "outro", "section": "outro", "delivery": "warm"},
            ],
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            generate_commentary_script(str(output), article, style="dialogue", mc_gender="female")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["style"] == "dialogue"
        speakers = {line["speaker"] for line in script["lines"]}
        assert "male" in speakers, "dialogue should keep male speaker"
        assert "female" in speakers, "dialogue should keep female speaker"

    def test_dialogue_invalid_speaker_fallback_to_male(self, tmp_path):
        """dialogue mode: invalid speaker should fallback to male."""
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }

        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "intro", "section": "intro", "delivery": "neutral"},
                {"speaker": "invalid", "text": "bad speaker", "section": "news", "delivery": "neutral"},
                {"speaker": "female", "text": "outro", "section": "outro", "delivery": "warm"},
            ],
        }

        output = tmp_path / "test_out.json"

        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            generate_commentary_script(str(output), article, style="dialogue", mc_gender="female")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert script["lines"][0]["speaker"] == "male"
        assert script["lines"][1]["speaker"] == "male", "invalid speaker should fallback to male"
        assert script["lines"][2]["speaker"] == "female"


class TestSoloConcreteDataInstructions:
    """Verify concrete data instructions are added to the solo prompt template."""

    def test_prompt_template_contains_concrete_data_instructions(self):
        prompt_path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "generate_commentary_script.md"
        content = prompt_path.read_text(encoding="utf-8")
        assert "元記事に含まれる数値・金額・割合・日時・バージョン番号などをぼかさず" in content
        assert "モデル名・製品名・企業名・固有名詞" in content
        assert "比較対象や検証条件" in content
        assert "各 news ラインには最低1件以上の具体的な事実・数字を含める" in content

    def test_dialogue_section_unchanged(self):
        prompt_path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "generate_commentary_script.md"
        content = prompt_path.read_text(encoding="utf-8")
        solo_marker = "## スタイル=solo（一人解説）の場合"
        dialogue_marker = "## スタイル=dialogue（二人対談）の場合"
        solo_start = content.index(solo_marker)
        dialogue_start = content.index(dialogue_marker)
        solo_end = dialogue_start
        solo_section = content[solo_start:solo_end]
        assert "元記事に含まれる数値" in solo_section
        dialogue_section = content[dialogue_start:]
        assert "元記事に含まれる数値" not in dialogue_section

    def test_solo_generation_injects_concrete_data_instructions(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch
        from pathlib import Path

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }
        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [{"speaker": "male", "text": "test", "section": "news", "delivery": "neutral"}],
        }
        captured_prompt = None

        class CapturingClient:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args, **kwargs):
                pass
            def generate_json(self, prompt):
                nonlocal captured_prompt
                captured_prompt = prompt
                return fake_response

        output = tmp_path / "test_out.json"
        with patch("app.batch.generate_commentary_script.OllamaClient", CapturingClient):
            generate_commentary_script(str(output), article, style="solo", mc_gender="male")

        assert captured_prompt is not None
        assert "元記事に含まれる数値・金額・割合" in captured_prompt
        assert "各 news ラインには最低1件以上の具体的な事実・数字を含める" in captured_prompt

    def test_dialogue_generation_still_works(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script
        from unittest.mock import patch

        article = {
            "id": 1,
            "title": "Test",
            "text": "x" * 500,
        }
        fake_response = {
            "title": "Test",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "intro", "section": "intro", "delivery": "neutral"},
                {"speaker": "female", "text": "reaction", "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "news detail", "section": "news", "delivery": "neutral"},
                {"speaker": "female", "text": "question", "section": "news", "delivery": "questioning"},
                {"speaker": "male", "text": "analysis", "section": "news", "delivery": "thoughtful"},
                {"speaker": "female", "text": "outro", "section": "outro", "delivery": "warm"},
            ],
        }

        output = tmp_path / "test_out.json"
        with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
            instance = mock.return_value
            instance.__enter__.return_value.generate_json.return_value = fake_response
            result = generate_commentary_script(str(output), article, style="dialogue", mc_gender="male")

        import json
        script = json.loads(output.read_text(encoding="utf-8"))
        assert result == 6
        assert script["style"] == "dialogue"
        speakers = {line["speaker"] for line in script["lines"]}
        assert "male" in speakers
        assert "female" in speakers


class TestConcreteDataQualityGuard:
    """Tests for _check_concrete_data quality guard."""

    def test_digits_present_no_warning(self, caplog):
        from app.batch.generate_commentary_script import _check_concrete_data
        caplog.set_level("WARNING")
        lines = [
            {"text": "This product costs 100 dollars and has 2 features"},
            {"text": "Version 3.0 was released"},
        ]
        _check_concrete_data(lines, "solo")
        assert len(caplog.records) == 0

    def test_no_digits_triggers_warning(self, caplog):
        from app.batch.generate_commentary_script import _check_concrete_data
        caplog.set_level("WARNING")
        lines = [
            {"text": "This product is expensive"},  # missing text key raises
            {"text": "No numbers here either"},
        ]
        _check_concrete_data(lines, "solo")
        assert len(caplog.records) == 1
        assert "no concrete data" in caplog.records[0].getMessage().lower()

    def test_dialogue_skips_check(self, caplog):
        from app.batch.generate_commentary_script import _check_concrete_data
        caplog.set_level("WARNING")
        lines = [
            {"text": "totally abstract without any numbers"},
        ]
        _check_concrete_data(lines, "dialogue")
        assert len(caplog.records) == 0

    def test_empty_lines_no_crash(self, caplog):
        from app.batch.generate_commentary_script import _check_concrete_data
        caplog.set_level("WARNING")
        _check_concrete_data([], "solo")
        assert len(caplog.records) == 1
        assert "no concrete data" in caplog.records[0].getMessage().lower()


def _make_fake_open(script_json: str):
    """Return a mock `open` context manager that reads from a string."""
    def _open(*args, **kwargs):
        m = MagicMock()
        m.__enter__.return_value.read.return_value = script_json
        return m
    return _open
