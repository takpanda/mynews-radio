
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

    def test_duplicate_date_returns_409_on_race_condition(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-03-03", status="generating")
        svc.update_episode_phase(eid, "summarize")

        # Simulate race: stale found, reset to pending, but claim fails.
        with patch.object(EpisodeService, "claim_generating_slot", return_value=False):
            r1 = client.post("/generate", json={"date": "2099-03-03"})
        assert r1.status_code == 409

    def test_duplicate_date_reuses_stale_episode(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-05-05", status="pending")
        svc.update_episode_status(eid, "generating")
        svc.update_episode_phase(eid, "summarize")

        # Second request on same date reuses the stale generating episode.
        r1 = client.post("/generate", json={"date": "2099-05-05"})
        assert r1.status_code == 200
        data = r1.json()
        assert data["episode_id"] == eid

    def test_stale_generating_episode_reused(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-04-04", status="generating")
        svc.update_episode_phase(eid, "summarize")
        r1 = client.post("/generate", json={"date": "2099-04-04"})
        assert r1.status_code == 200
        data = r1.json()
        assert data["episode_id"] == eid
        assert data["status"] == "generating"

    def test_duplicate_date_reuses_generating_episode(self, client):
        with patch("app.api.generate.asyncio.ensure_future"), \
             patch("threading.Thread.start"):
            r1 = client.post("/generate", json={"date": "2099-03-03"})
            assert r1.status_code == 200
            episode_id_1 = r1.json()["episode_id"]
            r2 = client.post("/generate", json={"date": "2099-03-03"})
            assert r2.status_code == 200
            episode_id_2 = r2.json()["episode_id"]
        assert episode_id_1 == episode_id_2

    def test_new_date_creates_episode(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        before = len(svc.get_episode_list())
        resp = client.post("/generate", json={"date": "2099-04-04"})
        assert resp.status_code == 200
        after = len(svc.get_episode_list())
        assert after == before + 1

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
    def test_revised_true_skips_synthesize_and_build(self, mock_import):
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-10-01", status="generating")
        body = GenerateRequest(date="2099-10-01")

        fake_script = '{"lines": [{"article_id": "1", "text": "Hello world"}]}'

        with patch("app.api.generate.summarize_articles", return_value=5), \
             patch("app.api.generate.generate_script", return_value=1), \
             patch("app.api.generate.synthesize_episode") as mock_synth, \
             patch("app.api.generate.build_episode") as mock_build, \
             patch("app.api.generate.review_script",
                   return_value={"revised": True, "review_count": 3}), \
             patch("shutil.copy"), \
             patch("builtins.open", _make_fake_open(fake_script)):

            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        mock_synth.assert_not_called()
        mock_build.assert_not_called()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "reviewed"
        assert ep["phase"] == "reviewed"

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
             patch("app.api.generate.synthesize_episode"), \
             patch("app.api.generate.build_episode"), \
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
