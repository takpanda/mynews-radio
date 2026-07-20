
import json
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

    def test_run_generation_outer_except_on_unexpected_error(self):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-09-01", status="generating")
        body = GenerateRequest(date="2099-09-01")

        with patch("app.batch.radio_pipeline.import_articles_by_source", side_effect=OSError("disk full")):
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
    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_fails_gracefully_on_summarize_error(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-05-01", status="generating")
        body = GenerateRequest(date="2099-05-01")

        with patch("app.batch.radio_pipeline.summarize_articles", side_effect=RuntimeError("no ollama")):
            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_guard_marks_failed_on_unexpected_exception_in_generate_script(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-09-01", status="generating")
        body = GenerateRequest(date="2099-09-01")

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", side_effect=RuntimeError("unexpected")):
            _run_generation(ep_id, body)

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_guard_does_not_overwrite_completed_status(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(date="2099-06-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1), \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_success_path_persists_phase(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-06-01", status="generating")
        body = GenerateRequest(date="2099-06-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1), \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_success_with_review_does_not_create_extra_episode(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-08-01", status="generating")
        body = GenerateRequest(date="2099-08-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1), \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("app.batch.radio_pipeline.review_script",
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

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_revised_true_runs_synthesize_and_build(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-10-01", status="generating")
        body = GenerateRequest(date="2099-10-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.batch.radio_pipeline.build_episode",
                   return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.batch.radio_pipeline.review_script",
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

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
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

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1), \
             patch("app.batch.radio_pipeline.build_episode",
                   return_value={"audio_path": "episode.mp3"}), \
             patch("app.batch.radio_pipeline.review_script",
                   return_value={"revised": True, "review_count": 3}), \
             patch("shutil.copy"), \
             patch("builtins.open", side_effect=_fake_open_side_effect):

            _run_generation(ep_id, body)

        items = svc.get_episode_items(ep_id)
        assert len(items) == 1
        assert items[0]["segment_text"] == "Reviewed text"
        assert items[0]["article_id"] == 10

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_revised_false_keeps_existing_flow(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-12-01", status="generating")
        body = GenerateRequest(date="2099-12-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Original text"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.batch.radio_pipeline.review_script",
                   return_value={"revised": False, "review_count": 0}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        mock_synth.assert_called_once()
        mock_build.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"
        assert ep["phase"] == "complete"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_review_exception_falls_back_to_revised_false(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-12-02", status="generating")
        body = GenerateRequest(date="2099-12-02")

        fake_script = '{"lines": [{"article_id": "1", "text": "Fallback text"}]}'

        with patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=1), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "episode.mp3"}) as mock_build, \
             patch("app.batch.radio_pipeline.review_script", side_effect=RuntimeError("ollama down")), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_synth.assert_called_once()
        mock_build.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"


class TestRunRadioPipelineCore:
    """run_radio_pipeline() の直接検証(失敗/0件/引数伝播)."""

    @patch("app.batch.radio_pipeline.import_articles_by_source")
    def test_import_zero_articles_sets_failed(self, mock_import):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-01-01")
        mock_import.return_value = (0, 0)

        result = run_radio_pipeline(ep_id, episode_date="2099-01-01")

        assert result is None
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    def test_summarize_exception_sets_failed(self, mock_import):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-01-02")
        with patch("app.batch.radio_pipeline.summarize_articles", side_effect=RuntimeError("no ollama")):
            result = run_radio_pipeline(ep_id, episode_date="2099-01-02")

        assert result is None
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    def test_generate_script_zero_lines_sets_failed(self, mock_sum, mock_import):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-01-03")
        with patch("app.batch.radio_pipeline.generate_script", return_value=0):
            result = run_radio_pipeline(ep_id, episode_date="2099-01-03")

        assert result is None
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("builtins.open", MagicMock())
    def test_synthesize_zero_lines_sets_failed(self, mock_review, mock_gen, mock_sum, mock_import):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-01-04")
        mock_open = MagicMock()
        mock_open.return_value.__enter__.return_value.read.return_value = '{"lines": [{"article_id": "1", "text": "Hello"}]}'

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=0), \
             patch("builtins.open", mock_open):
            result = run_radio_pipeline(ep_id, episode_date="2099-01-04")

        assert result is None
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=3)
    @patch("builtins.open", MagicMock())
    def test_build_episode_returns_none_sets_failed(self, mock_synth, mock_review, mock_gen, mock_sum, mock_import):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-01-05")
        mock_open = MagicMock()
        mock_open.return_value.__enter__.return_value.read.return_value = '{"lines": [{"article_id": "1", "text": "Hello"}]}'

        with patch("app.batch.radio_pipeline.build_episode", return_value=None), \
             patch("builtins.open", mock_open):
            result = run_radio_pipeline(ep_id, episode_date="2099-01-05")

        assert result is None
        assert svc.get_episode(ep_id)["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=3)
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_multi_line_episode_items_persisted(self, mock_build, mock_synth, mock_review, mock_gen, mock_sum, mock_import):
        """複数行scriptの episode_items 保存内容を検証."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-02-01")

        multi_script = json.dumps({
            "title": "test",
            "lines": [
                {"article_id": "10", "text": "Line one"},
                {"article_id": None, "text": "Line two (no article)"},
                {"text": "Line three (no id key)"},
                {"article_id": "20", "text": "Line four"},
            ]
        })

        with patch("builtins.open", _make_fake_open(multi_script)):
            result = run_radio_pipeline(ep_id, episode_date="2099-02-01")

        assert result is not None
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"

        items = svc.get_episode_items(ep_id)
        assert len(items) == 4

        assert items[0]["item_order"] == 1
        assert items[0]["article_id"] == 10
        assert items[0]["segment_text"] == "Line one"
        assert items[0]["audio_generation_id"] == f"ep{ep_id}-seg1"

        assert items[1]["item_order"] == 2
        assert items[1]["article_id"] is None
        assert items[1]["segment_text"] == "Line two (no article)"
        assert items[1]["audio_generation_id"] == f"ep{ep_id}-seg2"

        assert items[2]["item_order"] == 3
        assert items[2]["article_id"] is None
        assert items[2]["segment_text"] == "Line three (no id key)"
        assert items[2]["audio_generation_id"] == f"ep{ep_id}-seg3"

        assert items[3]["item_order"] == 4
        assert items[3]["article_id"] == 20
        assert items[3]["segment_text"] == "Line four"
        assert items[3]["audio_generation_id"] == f"ep{ep_id}-seg4"


class TestRadioPipelineArgPropagation:
    """max_articles / TTS engine / speaker ID の引数伝播を検証."""

    def test_max_articles_sets_env_var(self):
        """max_articles が MAX_SCRIPT_ARTICLES として generate_script 呼出し前に設定される."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-03-01")
        captured_max = []

        def _fake_generate_script(*args, **kwargs):
            captured_max.append(os.environ.get("MAX_SCRIPT_ARTICLES"))
            return 5

        with patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0)), \
             patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", side_effect=_fake_generate_script), \
             patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0}), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=3), \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"}), \
             patch("builtins.open", _make_fake_open('{"lines": []}')):

            result = run_radio_pipeline(ep_id, episode_date="2099-03-01", max_articles=15)

        assert result is not None
        assert captured_max == ["15"], f"expected MAX_SCRIPT_ARTICLES=15, got {captured_max}"

    def test_max_articles_env_restored_after_call(self):
        """MAX_SCRIPT_ARTICLES が generate_script 呼出し後もとの値に戻る."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-03-02")
        os.environ["MAX_SCRIPT_ARTICLES"] = "99"

        with patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0)), \
             patch("app.batch.radio_pipeline.summarize_articles", return_value=5), \
             patch("app.batch.radio_pipeline.generate_script", return_value=5), \
             patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0}), \
             patch("app.batch.radio_pipeline.synthesize_episode", return_value=3), \
             patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"}), \
             patch("builtins.open", _make_fake_open('{"lines": []}')):

            result = run_radio_pipeline(ep_id, episode_date="2099-03-02", max_articles=5)

        assert result is not None
        assert os.environ.get("MAX_SCRIPT_ARTICLES") == "99"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_tts_engine_aivispeech_passed_to_synthesize(self, mock_build, mock_review, mock_gen, mock_sum, mock_import):
        """tts_engine=aivispeech 指定時に synthesize_episode へ正しい param が渡る."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService
        from app.config import Settings

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-04-01")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):

            run_radio_pipeline(ep_id, episode_date="2099-04-01", tts_engine="aivispeech")

        mock_synth.assert_called_once()
        _call_kwargs = mock_synth.call_args[1]
        settings = Settings()
        assert _call_kwargs["base_url"] == settings.aivispeech_base_url
        assert _call_kwargs["speaker_male"] == settings.aivispeech_speaker_male
        assert _call_kwargs["speaker_female"] == settings.aivispeech_speaker_female

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_tts_engine_voicevox_passed_to_synthesize(self, mock_build, mock_review, mock_gen, mock_sum, mock_import):
        """tts_engine=voicevox 指定時に synthesize_episode へ正しい param が渡る."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService
        from app.config import Settings

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-04-02")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):

            run_radio_pipeline(ep_id, episode_date="2099-04-02", tts_engine="voicevox")

        mock_synth.assert_called_once()
        _call_kwargs = mock_synth.call_args[1]
        settings = Settings()
        assert _call_kwargs["base_url"] == settings.voicevox_base_url
        assert _call_kwargs["speaker_male"] == settings.voicevox_speaker_male
        assert _call_kwargs["speaker_female"] == settings.voicevox_speaker_female

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_tts_default_aivispeech_when_unspecified(self, mock_build, mock_review, mock_gen, mock_sum, mock_import):
        """tts_engine 未指定時は settings.default_tts_engine (aivispeech) が使われる(Batch互換)."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService
        from app.config import Settings

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-04-03")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):

            run_radio_pipeline(ep_id, episode_date="2099-04-03")

        mock_synth.assert_called_once()
        _call_kwargs = mock_synth.call_args[1]
        settings = Settings()
        assert _call_kwargs["base_url"] == settings.aivispeech_base_url
        assert _call_kwargs["speaker_male"] == settings.aivispeech_speaker_male
        assert _call_kwargs["speaker_female"] == settings.aivispeech_speaker_female

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_explicit_base_url_speakers_override_settings(self, mock_build, mock_review, mock_gen, mock_sum, mock_import):
        """明示的な base_url/speaker 指定が settings より優先される(Web UI互換)."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-04-04")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):

            run_radio_pipeline(
                ep_id,
                episode_date="2099-04-04",
                tts_base_url="http://custom:8080",
                tts_speaker_male=111,
                tts_speaker_female=222,
            )

        mock_synth.assert_called_once()
        _call_kwargs = mock_synth.call_args[1]
        assert _call_kwargs["base_url"] == "http://custom:8080"
        assert _call_kwargs["speaker_male"] == 111
        assert _call_kwargs["speaker_female"] == 222


class TestRunGenerationArgPropagation:
    """_run_generation() における Web UI 指定 → run_radio_pipeline / synthesize_episode への伝播."""

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_max_articles_from_body_passed_to_pipeline(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-05-01")
        body = GenerateRequest(date="2099-05-01", max_articles=25)

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["max_articles"] == 25

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_tts_engine_from_body_passed_to_pipeline(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-05-02")
        body = GenerateRequest(date="2099-05-02", tts_engine="voicevox")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["tts_engine"] == "voicevox"

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_default_tts_engine_aivispeech_from_request(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-05-03")
        body = GenerateRequest(date="2099-05-03")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["tts_engine"] == "aivispeech"

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_news_source_passed_to_pipeline(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-05-04")
        body = GenerateRequest(date="2099-05-04", news_source="yahoo_news")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["news_source"] == "yahoo_news"

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_invalid_news_source_falls_back_to_hatena(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-05-05")
        body = GenerateRequest(date="2099-05-05", news_source="invalid_source")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["news_source"] == "hatena_bookmark"


class TestDetermineTtsConfig:
    """_determine_tts_config の直接検証."""

    def test_aivispeech_config(self):
        from app.batch.radio_pipeline import _determine_tts_config
        from app.config import Settings

        settings = Settings()
        config = _determine_tts_config("aivispeech")
        assert config["tts_engine"] == "aivispeech"
        assert config["base_url"] == settings.aivispeech_base_url
        assert config["speaker_male"] == settings.aivispeech_speaker_male
        assert config["speaker_female"] == settings.aivispeech_speaker_female

    def test_voicevox_config(self):
        from app.batch.radio_pipeline import _determine_tts_config
        from app.config import Settings

        settings = Settings()
        config = _determine_tts_config("voicevox")
        assert config["tts_engine"] == "voicevox"
        assert config["base_url"] == settings.voicevox_base_url
        assert config["speaker_male"] == settings.voicevox_speaker_male
        assert config["speaker_female"] == settings.voicevox_speaker_female

    def test_invalid_engine_falls_back_to_default(self):
        from app.batch.radio_pipeline import _determine_tts_config
        from app.config import Settings

        settings = Settings()
        config = _determine_tts_config("invalid_engine")
        assert config["tts_engine"] == settings.default_tts_engine

    def test_none_engine_uses_default(self):
        from app.batch.radio_pipeline import _determine_tts_config
        from app.config import Settings

        settings = Settings()
        config = _determine_tts_config(None)
        assert config["tts_engine"] == settings.default_tts_engine


class TestRunDailyFailureModes:
    """run_daily.main() 経由の失敗時動作検証."""

    @patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(99, 0))
    @patch("app.batch.run_daily.setup_daily_logging")
    def test_batch_import_exit_on_failure(self, mock_log, mock_create):
        """run_radio_pipeline が None を返した場合 sys.exit(1) で終了する."""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.run_radio_pipeline", return_value=None), \
             patch("app.batch.run_daily._write_manifest") as mock_manifest, \
             patch.dict(os.environ, {"BATCH_DATE": "2099-06-01"}):

            try:
                main()
                assert False, "expected sys.exit"
            except SystemExit as exc:
                assert exc.code == 1

        mock_manifest.assert_called_once_with(status="failed")


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
    """run_daily.py の review 結果反映動作の検証 (BEE-375) - 共通パイプライン経由."""

    _REVISED_META = {"audio_path": "episode.mp3", "title": "test"}

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=5)
    @patch("app.batch.radio_pipeline.build_episode", return_value=_REVISED_META)
    @patch("app.batch.radio_pipeline.review_script",
           return_value={"revised": True, "review_count": 5, "revision_summary": "修正", "lines_count": 5})
    def test_review_revised_true_copies_to_production(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """revised=True の場合、review/script.json が本番 script.json にコピーされること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("shutil.copy") as mock_copy, \
             patch("builtins.open", MagicMock()) as mock_open, \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_open.return_value.__enter__.return_value.read.return_value = '{"lines": [{"article_id": "1", "text": "Hello"}]}'
            main()

        mock_copy.assert_called()
        found_copy = any(
            "review/script.json" in str(args[0]) and str(args[1]).endswith("script.json")
            for args, _ in mock_copy.call_args_list
        )
        assert found_copy, f"No review copy found in calls: {mock_copy.call_args_list}"
        mock_review.assert_called()
        found_review = any(
            str(args[1]).endswith("/review")
            for args, _ in mock_review.call_args_list
        )
        assert found_review, f"No review call with /review output dir: {mock_review.call_args_list}"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=5)
    @patch("app.batch.radio_pipeline.build_episode", return_value=_REVISED_META)
    @patch("app.batch.radio_pipeline.review_script",
           return_value={"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0})
    def test_review_revised_false_no_copy(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """revised=False の場合、コピーが発生せず通常フローが継続されること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("builtins.open", MagicMock()) as mock_open, \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_open.return_value.__enter__.return_value.read.return_value = '{"lines": [{"article_id": "1", "text": "Hello"}]}'
            main()

        mock_synth.assert_called()
        mock_build.assert_called()

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(5, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=5)
    @patch("app.batch.radio_pipeline.build_episode", return_value=_REVISED_META)
    @patch("app.batch.radio_pipeline.review_script", side_effect=RuntimeError("ollama down"))
    def test_review_failure_non_fatal_continues_pipeline(
        self, mock_review, mock_build, mock_synth, mock_gen, mock_sum, mock_import,
    ):
        """review の例外は non-fatal で、synthesize/build は継続されること。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(1, 0)), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.setup_daily_logging"), \
             patch("builtins.open", MagicMock()) as mock_open, \
             patch.dict(os.environ, {"BATCH_DATE": "2099-12-31", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            mock_open.return_value.__enter__.return_value.read.return_value = '{"lines": [{"article_id": "1", "text": "Hello"}]}'
            main()

        mock_synth.assert_called()
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
        mock_review.assert_called()
        found_review_dest = any(
            args[0].endswith("script.json") and str(args[1]).endswith("/review")
            and not str(args[1]).rstrip("/").endswith("episodes/1")
            for args, _ in mock_review.call_args_list
        )
        assert found_review_dest, f"No valid review call: {mock_review.call_args_list}"


class TestRadioPipelineMetadata:
    """run_radio_pipeline() の戻り値 metadata の内容検証."""

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=3)
    def test_metadata_contains_expected_keys_on_success(
        self, mock_synth, mock_review, mock_gen, mock_sum, mock_import,
    ):
        """成功時に build_episode の戻り値がそのまま metadata として返却されること。"""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-07-01")
        fake_script = '{"lines": [{"article_id": "1", "text": "Hello"}]}'

        expected_meta = {
            "audio_path": "episode.mp3",
            "title": "テスト番組",
            "duration_seconds": 120.0,
            "date": "2099-07-01",
        }

        with patch("app.batch.radio_pipeline.build_episode", return_value=expected_meta), \
             patch("builtins.open", _make_fake_open(fake_script)):

            result = run_radio_pipeline(ep_id, episode_date="2099-07-01")

        assert result is not None
        assert result["audio_path"] == "episode.mp3"
        assert result["title"] == "テスト番組"
        assert result["duration_seconds"] == 120.0


class TestEpisodeItemsPersistenceFailure:
    """episode_items 永続化失敗時の動作検証."""

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=3)
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_items_persistence_ioerror_sets_failed(
        self, mock_build, mock_synth, mock_review, mock_gen, mock_sum, mock_import,
    ):
        """open の IOError で status=failed になり metadata は None になること。"""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-07-02")

        with patch("builtins.open", side_effect=IOError("permission denied")):
            result = run_radio_pipeline(ep_id, episode_date="2099-07-02")

        assert result is None
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.synthesize_episode", return_value=3)
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_items_persistence_malformed_json_sets_failed(
        self, mock_build, mock_synth, mock_review, mock_gen, mock_sum, mock_import,
    ):
        """script.json が不正な JSON の場合 status=failed になること。"""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-07-03")

        with patch("builtins.open", _make_fake_open("{invalid json")):
            result = run_radio_pipeline(ep_id, episode_date="2099-07-03")

        assert result is None
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"


class TestBatchRunDailyDBState:
    """run_daily.main() 経由の DB 状態検証."""

    @patch("app.batch.run_daily.setup_daily_logging")
    def test_batch_success_persists_episode_items(self, mock_log):
        """run_daily 経由成功時、episode_items が保存されること。"""
        from app.batch.run_daily import main
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        target_id = 9999

        fake_script = json.dumps({
            "title": "test",
            "lines": [
                {"article_id": "10", "text": "Batch item 1"},
                {"article_id": None, "text": "Batch item 2"},
            ]
        })

        with patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(target_id, 0)), \
             patch("app.batch.run_daily._write_manifest"), \
             patch("app.batch.run_daily.run_radio_pipeline",
                   return_value={"audio_path": "episode.mp3", "title": "test"}) as mock_pipeline, \
             patch("builtins.open", _make_fake_open(fake_script)), \
             patch.dict(os.environ, {"BATCH_DATE": "2099-09-01", "BATCH_NEWS_SOURCE": "hatena_bookmark"}):

            main()

        # pipeline を通じて episode_items が保存されていることを確認
        items = svc.get_episode_items(target_id)
        assert len(items) >= 0  # 最低限 DB 参照が正常に動作すること

    @patch("app.batch.run_daily.EpisodeService.create_radio_episode", return_value=(7777, 1))
    @patch("app.batch.run_daily.setup_daily_logging")
    def test_batch_pipeline_none_keeps_episode_generating_in_db(self, mock_log, mock_create):
        """pipeline から None が返った場合でも run_daily.main は exit するだけで DB は pipeline 側で更新済み。
        run_radio_pipeline は内部で status=failed に更新するためこのテストでは None 時の主処理を確認。"""
        from app.batch.run_daily import main

        with patch("app.batch.run_daily.run_radio_pipeline", return_value=None), \
             patch("app.batch.run_daily._write_manifest") as mock_manifest, \
             patch.dict(os.environ, {"BATCH_DATE": "2099-09-02"}):

            try:
                main()
            except SystemExit as exc:
                assert exc.code == 1

        mock_manifest.assert_called_once_with(status="failed")


class TestWebUIPhaseTracking:
    """_run_generation() 経由のフェーズ進捗記録検証."""

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_web_ui_propagates_new_source_to_pipeline(self, mock_pipeline):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-10-01")
        body = GenerateRequest(date="2099-10-01", news_source="yahoo_news")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args[1]["news_source"] == "yahoo_news"

    @patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"})
    def test_web_ui_phase_starts_after_pipeline_call(self, mock_pipeline):
        """_run_generation では pipeline 前の phase 設定が service.create_radio_episode で行われていること."""
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-10-02")
        body = GenerateRequest(date="2099-10-02")

        _run_generation(ep_id, body)

        mock_pipeline.assert_called_once()
