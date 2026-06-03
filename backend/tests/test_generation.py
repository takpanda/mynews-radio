
import time
from unittest.mock import patch, MagicMock


class TestGenerateEndpoint:
    def test_post_generate_returns_json_not_sse(self, client):
        """POST /generate must return JSON immediately with episode_id and status."""
        resp = client.post("/generate", json={
            "date": "2099-01-01",
            "max_articles": 5,
            "enable_review": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "episode_id" in data and "status" in data and "message" in data
        assert data["status"] == "generating"
        assert isinstance(data["episode_id"], int)

    def test_post_generate_returns_under_1s(self, client):
        """The endpoint must be fast (< 1 s) because the pipeline runs in background."""
        start = time.time()
        resp = client.post("/generate", json={"date": "2099-02-02"})
        elapsed = time.time() - start
        assert resp.status_code == 200 and elapsed < 1.0


    def test_duplicate_date_returns_409(self, client):
        """Two requests for the same date: first succeeds, second gets 409."""
        r1 = client.post("/generate", json={"date": "2099-03-03"})
        assert r1.status_code == 200
        r2 = client.post("/generate", json={"date": "2099-03-03"})
        assert r2.status_code == 409


class TestEpisodePhase:
    def test_get_episode_returns_phase(self, client):
        """GET /episodes/{id} must include the new 'phase' field."""
        from app.services.episode_service import EpisodeService

        eid = EpisodeService().create_episode(episode_date="2099-06-01", status="generating")
        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "phase" in data and isinstance(data["phase"], str)


class TestEpisodeServicePhase:
    def test_update_episode_phase(self, client):
        """update_episode_phase persists to DB and is readable on next select."""
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
        """Create + update_episode_status still work (what batch pipelines use)."""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode("2099-10-01", status="pending")
        svc.update_episode_status(eid, "completed")
        assert svc.get_episode(eid)["status"] == "completed"


class TestRunGenerationPipeline:
    @patch(
        "app.api.generate.import_articles_by_source", return_value=(3, 0)
    )
    def test_fails_gracefully_on_summarize_error(self, mock_import):
        """If summarize fails, status becomes 'failed' promptly."""
        from app.api.generate import _run_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-05-01", status="generating")
        body = GenerateRequest(date="2099-05-01")

        with patch(
            "app.api.generate.summarize_articles", side_effect=RuntimeError("no ollama")
        ):
            _run_generation(ep_id, body)

        mock_import.assert_called_once()
        ep = svc.get_episode(ep_id)
        assert ep["status"] == "failed"
