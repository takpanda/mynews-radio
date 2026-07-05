
import os
import time
from unittest.mock import patch, MagicMock


class TestGenerateEndpoint:
    def test_post_generate_returns_json_not_sse(self, client):
        resp = client.post("/generate", json={
            "date": "2099-01-01",
            "max_articles": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data and "status" in data and "message" in data
        assert data["status"] == "generating"
        assert isinstance(data["episode_id"], int)

    def test_post_generate_returns_under_1s(self, client):
        start = time.time()
        resp = client.post("/generate", json={"date": "2099-02-02"})
        elapsed = time.time() - start
        assert resp.status_code == 200 and elapsed < 1.0

    def test_duplicate_date_creates_new_episode(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-03-03", status="pending")

        # With new logic, second request creates a new episode.
        r1 = client.post("/generate", json={"date": "2099-03-03"})
        assert r1.status_code == 200
        data = r1.json()
        assert data["episode_id"] != eid

    def test_duplicate_date_creates_new_episode_with_seq(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid1 = svc.create_episode(episode_date="2099-05-05", status="completed")

        # Second request on same date creates a new episode with seq=1.
        r1 = client.post("/generate", json={"date": "2099-05-05", "max_articles": 5})
        assert r1.status_code == 200
        data = r1.json()
        assert data["episode_id"] != eid1
        ep = svc.get_episode(data["episode_id"])
        assert ep["seq"] == 1

    def test_stale_generating_episode_creates_new(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid1 = svc.create_episode(episode_date="2099-04-04", status="generating")
        svc.update_episode_phase(eid1, "summarize")
        r1 = client.post("/generate", json={"date": "2099-04-04", "max_articles": 5})
        assert r1.status_code == 200
        data = r1.json()
        assert data["episode_id"] != eid1

    def test_new_date_creates_episode_with_seq_0(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        before = len(svc.get_episode_list())
        resp = client.post("/generate", json={"date": "2099-04-04", "max_articles": 5})
        assert resp.status_code == 200
        data = resp.json()
        after = len(svc.get_episode_list())
        assert after == before + 1
        ep = svc.get_episode(data["episode_id"])
        assert ep["seq"] == 0

    def test_run_generation_outer_except_on_unexpected_error(self, client):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-09-01", status="generating")
        body = GenerateRequest(date="2099-09-01")

        # Patch an early operation outside any inner try-except so the outer
        # except catches it and sets status to "failed".
        with patch("pathlib.Path.mkdir", side_effect=OSError("disk full")):
            _run_generation(ep_id, body)

        assert svc.get_episode(ep_id)["status"] == "failed"


class TestEpisodePhase:
    def test_get_episode_returns_phase(self, client):
        from app.services.episode_service import EpisodeService

        eid = EpisodeService().create_episode(episode_date="2099-06-01", status="generating")
        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "phase" in data and isinstance(data["phase"], str)


class TestEpisodeServicePhase:
    def test_update_episode_phase(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-07-01", status="generating")
        svc.update_episode_phase(eid, "summarize")
        ep = svc.get_episode(eid)
        assert ep is not None and ep["phase"] == "summarize"


class TestBatchPipelineUnaffected:
    def test_run_daily_imports_cleanly(self):
        import app.batch.run_daily  # noqa

    def test_orchestrate_module_imports_cleanly(self):
        from app.batch import orchestrate  # noqa

    def test_batch_api_still_works(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode("2099-10-01", status="pending")
        svc.update_episode_status(eid, "completed")
        assert svc.get_episode(eid)["status"] == "completed"


def _make_fake_open(script_json: str):
    """Return a mock `open` context manager that reads from a string."""
    def _open(*args, **kwargs):
        m = MagicMock()
        m.__enter__.return_value.read.return_value = script_json
        return m
    return _open


class TestRunGenerationPipeline:
    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_fails_gracefully_on_summarize_error(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-05-01", status="generating")
        body = GenerateRequest(date="2099-05-01")

        with patch("app.api.generate.summarize_articles", side_effect=RuntimeError("no ollama")):
            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_guard_marks_failed_on_unexpected_exception_in_generate_script(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-09-01", status="generating")
        body = GenerateRequest(date="2099-09-01")

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", side_effect=RuntimeError("unexpected")):
            _run_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_guard_does_not_overwrite_completed_status(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(date="2099-06-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1), \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_success_path_persists_phase(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(date="2099-06-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1), \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_success_with_review_does_not_create_extra_episode(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-08-01", status="generating")
        body = GenerateRequest(date="2099-08-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1), \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("app.api.generate.review_script",
                   return_value={"revised": False, "review_count": 0}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

        # No separate review episode record should be created
        episodes = svc.get_episode_list()
        reviewed = [e for e in episodes if e["id"] != ep_id]
        assert len(reviewed) == 0

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_revised_true_runs_synthesize_and_build(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-10-01", status="generating")
        body = GenerateRequest(date="2099-10-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.api.generate.build_episode",
                   return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.api.generate.review_script",
                   return_value={"revised": True, "review_count": 3}), \
             patch("shutil.copy"), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_revised_true_persists_items_from_reviewed_script(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-11-01", status="generating")
        body = GenerateRequest(date="2099-11-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'
        reviewed_script = '{"title": "Reviewed", "lines": [{"article_id": "10", "text": "Reviewed text"}]}'

        def _fake_open_side_effect(*args, **kwargs):
            m = MagicMock()
            m.__enter__.return_value.read.return_value = reviewed_script
            return m

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1), \
             patch("app.api.generate.build_episode",
                   return_value={"audio_path": "episode.mp3"}), \
             patch("app.api.generate.review_script",
                   return_value={"revised": True, "review_count": 3}), \
             patch("shutil.copy"), \
             patch("builtins.open", side_effect=_fake_open_side_effect):

            _run_generation(ep_id, body)

        items = svc.get_episode_items(ep_id)
        assert len(items) == 1
        assert items[0]["segment_text"] == "Reviewed text"
        assert items[0]["article_id"] == 10

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_revised_false_keeps_existing_flow(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-12-01", status="generating")
        body = GenerateRequest(date="2099-12-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Original text"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.api.generate.review_script",
                   return_value={"revised": False, "review_count": 0}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.api.generate.import_articles_by_source", return_value=(3, 0))
    def test_review_exception_falls_back_to_revised_false(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-12-02", status="generating")
        body = GenerateRequest(date="2099-12-02")

        fake_script = '{"lines": [{"article_id": "1", "text": "Fallback text"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.api.generate.review_script", side_effect=RuntimeError("ollama down")), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_synth.assert_called_once()
        mock_build.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"


class TestAuthGuard:
    def test_no_api_key_skips_auth_compatibility(self, client):
        resp = client.post("/generate", json={"date": "2099-12-31", "max_articles": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data

    def test_missing_auth_header_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post("/generate", json={"date": "2099-12-31", "max_articles": 5})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid or missing API key"}

    def test_wrong_api_key_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post(
            "/generate",
            json={"date": "2099-12-31", "max_articles": 5},
            headers={"Authorization": "Bearer wrong-key-999"},
        )
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid or missing API key"}

    def test_valid_api_key_succeeds(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post(
            "/generate",
            json={"date": "2099-12-31", "max_articles": 5},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data

    def test_get_endpoints_are_not_protected(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.get("/episodes")
        assert resp.status_code == 200

    def test_synthesize_without_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post("/episodes/999/synthesize", json={"tts_engine": "voicevox"})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid or missing API key"}

    def test_synthesize_with_valid_auth_returns_streaming(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key-123")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post(
            "/episodes/999/synthesize",
            json={"tts_engine": "voicevox"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")


class TestRateLimit:
    def test_generate_exceeds_rate_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "0/minute")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post("/generate", json={"date": "2099-12-01", "max_articles": 5})
        assert resp.status_code == 429
        assert resp.json() == {"detail": "Rate limit exceeded. Try again later."}

    def test_rate_limit_clears_after_limit_increase(self, client, monkeypatch):
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "0/minute")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post("/generate", json={"date": "2099-12-03", "max_articles": 5})
        assert resp.status_code == 429

        monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")
        get_settings.cache_clear()

        resp2 = client.post("/generate", json={"date": "2099-12-04", "max_articles": 5})
        assert resp2.status_code == 200

    def test_get_endpoints_not_rate_limited(self, client, monkeypatch):
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "1/minute")
        from app.config import get_settings
        get_settings.cache_clear()

        client.post("/generate", json={"date": "2099-12-06", "max_articles": 5})
        client.post("/generate", json={"date": "2099-12-07", "max_articles": 5})

        resp = client.get("/episodes")
        assert resp.status_code == 200

    def test_synthesize_exceeds_rate_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "0/minute")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = client.post("/episodes/1/synthesize", json={"tts_engine": "voicevox"})
        assert resp.status_code == 429
        assert resp.json() == {"detail": "Rate limit exceeded. Try again later."}


class TestRunDailyReviewConsistency:
    """run_daily.py の review 結果反映動作の検証 (BEE-375)."""

    @patch("app.batch.run_daily.run_health_checks", return_value=[])
    @patch("app.batch.run_daily.summarize_articles", return_value=5)
    @patch("app.batch.run_daily.generate_script", return_value=5)
    @patch("app.batch.run_daily.synthesize_voicevox", return_value=5)
    @patch("app.batch.run_daily.build_episode", return_value={"audio_path": "episode.mp3"})
    @patch("app.batch.run_daily.review_script",
           return_value={"revised": True, "review_count": 5, "revision_summary": "修正", "lines_count": 5})
    def test_review_revised_true_copies_to_production(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_health,
    ):
        """revised=True の場合、review/script.json が本番 script.json にコピーされること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily.EpisodeService.update_episode_status"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_phase"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_audio_path"), \
             patch("app.batch.run_daily.EpisodeService.get_episode", return_value={"status": "generating"}), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("app.batch.run_daily.get_settings") as mock_settings, \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.run_daily.override_script_title"), \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_settings_instance = mock_settings.return_value
            mock_settings_instance.default_tts_engine = "aivispeech"
            mock_settings_instance.ollama_base_url = "http://localhost:11434"
            mock_settings_instance.ollama_model = "test-model"
            mock_settings_instance.aivispeech_base_url = "http://localhost:10101"
            mock_settings_instance.voicevox_base_url = "http://localhost:50021"

            main()

        # Verify review/script.json was copied to production script.json
        mock_copy.assert_called_once()
        call_args = mock_copy.call_args[0]
        assert "review/script.json" in call_args[0]
        assert call_args[1].endswith("script.json")
        mock_review.assert_called_once()

    @patch("app.batch.run_daily.run_health_checks", return_value=[])
    @patch("app.batch.run_daily.summarize_articles", return_value=5)
    @patch("app.batch.run_daily.generate_script", return_value=5)
    @patch("app.batch.run_daily.synthesize_voicevox", return_value=5)
    @patch("app.batch.run_daily.build_episode", return_value={"audio_path": "episode.mp3"})
    @patch("app.batch.run_daily.review_script",
           return_value={"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0})
    def test_review_revised_false_no_copy(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_health,
    ):
        """revised=False の場合、コピーが発生せず通常フローが継続されること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily.EpisodeService.update_episode_status"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_phase"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_audio_path"), \
             patch("app.batch.run_daily.EpisodeService.get_episode", return_value={"status": "generating"}), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("app.batch.run_daily.get_settings") as mock_settings, \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.run_daily.override_script_title"), \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_settings_instance = mock_settings.return_value
            mock_settings_instance.default_tts_engine = "aivispeech"
            mock_settings_instance.ollama_base_url = "http://localhost:11434"
            mock_settings_instance.ollama_model = "test-model"
            mock_settings_instance.aivispeech_base_url = "http://localhost:10101"
            mock_settings_instance.voicevox_base_url = "http://localhost:50021"

            main()

        mock_copy.assert_not_called()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()

    @patch("app.batch.run_daily.run_health_checks", return_value=[])
    @patch("app.batch.run_daily.summarize_articles", return_value=5)
    @patch("app.batch.run_daily.generate_script", return_value=5)
    @patch("app.batch.run_daily.synthesize_voicevox", return_value=5)
    @patch("app.batch.run_daily.build_episode", return_value={"audio_path": "episode.mp3"})
    @patch("app.batch.run_daily.review_script", side_effect=RuntimeError("ollama down"))
    def test_review_failure_non_fatal_continues_pipeline(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_health,
    ):
        """review の例外は non-fatal で、synthesize/build は継続されること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily.EpisodeService.update_episode_status"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_phase"), \
             patch("app.batch.run_daily.EpisodeService.update_episode_audio_path"), \
             patch("app.batch.run_daily.EpisodeService.get_episode", return_value={"status": "generating"}), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("app.batch.run_daily.get_settings") as mock_settings, \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.run_daily.override_script_title"), \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_settings_instance = mock_settings.return_value
            mock_settings_instance.default_tts_engine = "aivispeech"
            mock_settings_instance.ollama_base_url = "http://localhost:11434"
            mock_settings_instance.ollama_model = "test-model"
            mock_settings_instance.aivispeech_base_url = "http://localhost:10101"
            mock_settings_instance.voicevox_base_url = "http://localhost:50021"

            main()

        mock_copy.assert_not_called()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()


class TestOrchestrateReviewConsistency:
    """orchestrate.py の review 結果反映動作の検証 (BEE-375)."""

    @patch("app.batch.orchestrate.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.orchestrate.summarize_articles", return_value=5)
    @patch("app.batch.orchestrate.generate_script", return_value=5)
    @patch("app.batch.orchestrate.synthesize_episode", return_value=5)
    @patch("app.batch.orchestrate.build_episode", return_value={"duration_seconds": 120.0})
    def test_orchestrate_review_revised_true_copies_to_production(
        self, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """orchestrate.py: revised=True の場合、review/script.json が本番script.jsonにコピーされること。"""
        from app.batch.orchestrate import run

        with patch("app.batch.orchestrate._create_episode_record", return_value=(1, 0)), \
             patch("app.batch.orchestrate._set_episode_status"), \
             patch("app.batch.orchestrate._update_episode_audio"), \
             patch("app.batch.orchestrate.review_script",
                   return_value={"revised": True, "review_count": 5, "revision_summary": "修正", "lines_count": 5}), \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.orchestrate.override_script_title"), \
             patch("app.batch.orchestrate.Path.mkdir"):

            run("2099-12-31")

        # Verify review/script.json was copied to production script.json
        mock_copy.assert_called_once()
        call_args = mock_copy.call_args[0]
        assert "review/script.json" in call_args[0]
        assert call_args[1].endswith("script.json")
        # Verify synthesize/build still run even when revised=True
        mock_synth.assert_called_once()
        mock_build.assert_called_once()

    @patch("app.batch.orchestrate.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.orchestrate.summarize_articles", return_value=5)
    @patch("app.batch.orchestrate.generate_script", return_value=5)
    @patch("app.batch.orchestrate.synthesize_episode", return_value=5)
    @patch("app.batch.orchestrate.build_episode", return_value={"duration_seconds": 120.0})
    def test_orchestrate_review_revised_false_no_copy(
        self, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """orchestrate.py: revised=False の場合、コピーが発生せず通常フローが継続されること。"""
        from app.batch.orchestrate import run

        with patch("app.batch.orchestrate._create_episode_record", return_value=(1, 0)), \
             patch("app.batch.orchestrate._set_episode_status"), \
             patch("app.batch.orchestrate._update_episode_audio"), \
             patch("app.batch.orchestrate.review_script",
                   return_value={"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0}), \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.orchestrate.override_script_title"), \
             patch("app.batch.orchestrate.Path.mkdir"):

            run("2099-12-31")

        mock_copy.assert_not_called()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()

    @patch("app.batch.orchestrate.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.orchestrate.summarize_articles", return_value=5)
    @patch("app.batch.orchestrate.generate_script", return_value=5)
    @patch("app.batch.orchestrate.synthesize_episode", return_value=5)
    @patch("app.batch.orchestrate.build_episode", return_value={"duration_seconds": 120.0})
    @patch("app.batch.orchestrate.review_script", side_effect=RuntimeError("ollama down"))
    def test_orchestrate_review_failure_non_fatal(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """orchestrate.py: review の例外は non-fatal で、synthesize/build は継続されること。"""
        from app.batch.orchestrate import run

        with patch("app.batch.orchestrate._create_episode_record", return_value=(1, 0)), \
             patch("app.batch.orchestrate._set_episode_status"), \
             patch("app.batch.orchestrate._update_episode_audio"), \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.orchestrate.override_script_title"), \
             patch("app.batch.orchestrate.Path.mkdir"):

            run("2099-12-31")

        mock_copy.assert_not_called()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()

    @patch("app.batch.orchestrate.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.orchestrate.summarize_articles", return_value=5)
    @patch("app.batch.orchestrate.generate_script", return_value=5)
    @patch("app.batch.orchestrate.synthesize_episode", return_value=5)
    @patch("app.batch.orchestrate.build_episode", return_value={"duration_seconds": 120.0})
    def test_orchestrate_review_writes_to_review_subdirectory(
        self, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """orchestrate.py: review 出力先が review/ サブディレクトリであること。"""
        from app.batch.orchestrate import run

        with patch("app.batch.orchestrate._create_episode_record", return_value=(1, 0)), \
             patch("app.batch.orchestrate._set_episode_status"), \
             patch("app.batch.orchestrate._update_episode_audio"), \
             patch("app.batch.orchestrate.review_script") as mock_review, \
             patch("shutil.copy") as mock_copy, \
             patch("app.batch.orchestrate.override_script_title"), \
             patch("app.batch.orchestrate.Path.mkdir"):

            run("2099-12-31")

        # Verify review output dir is episode_dir/review/, not episode_dir directly
        mock_review.assert_called_once()
        call_args = mock_review.call_args[0]
        assert call_args[0].endswith("script.json")  # source script
        assert call_args[1].endswith("/review")       # output dir
        assert not call_args[1].endswith("episodes/1")  # not episode_dir directly
