import json
from unittest.mock import patch

import pytest


class TestEpisodeCategories:
    def test_validation_filters_unknown_duplicate_and_limits_three(self):
        from app.services.episode_category_service import validate_episode_categories

        assert validate_episode_categories([
            "テック・IT", "不正カテゴリ", "テック・IT", "AI・先端技術",
            "経済・金融", "政治・行政",
        ]) == ["テック・IT", "AI・先端技術", "経済・金融"]

    def test_create_defaults_to_empty_json_array(self, client):
        from app.services.episode_service import EpisodeService

        episode_id = EpisodeService().create_episode("2099-01-01")
        episode = EpisodeService().get_episode(episode_id)
        assert json.loads(episode["categories"]) == []

    def test_update_categories_persists_normalized_json(self, client):
        from app.services.episode_service import EpisodeService

        service = EpisodeService()
        episode_id = service.create_episode("2099-01-02")
        service.update_episode_categories(
            episode_id, ["AI・先端技術", "AI・先端技術", "unknown", "テック・IT"]
        )
        assert json.loads(service.get_episode(episode_id)["categories"]) == [
            "AI・先端技術", "テック・IT"
        ]

    @pytest.mark.parametrize("response", [[], "not-json", None])
    def test_non_dict_llm_response_falls_back_to_empty(self, response, tmp_path):
        from app.services.episode_category_service import select_episode_categories

        script = tmp_path / "script.json"
        summaries = tmp_path / "summaries.json"
        script.write_text(json.dumps({"lines": [{"text": "AIのニュース"}]}), encoding="utf-8")
        summaries.write_text("[]", encoding="utf-8")

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def generate_json(self, prompt): return response

        assert select_episode_categories(str(script), str(summaries), client_factory=FakeClient) == []

    def test_llm_exception_falls_back_to_empty(self, tmp_path):
        from app.services.episode_category_service import select_episode_categories

        script = tmp_path / "script.json"
        summaries = tmp_path / "summaries.json"
        script.write_text(json.dumps({"lines": [{"text": "AIのニュース"}]}), encoding="utf-8")
        summaries.write_text("[]", encoding="utf-8")

        class FailingClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def generate_json(self, prompt): raise RuntimeError("ollama unavailable")

        assert select_episode_categories(str(script), str(summaries), client_factory=FailingClient) == []

    def test_pipeline_continues_when_category_selection_fails(self, client, tmp_path):
        from app.batch import radio_pipeline
        from app.services.episode_service import EpisodeService

        service = EpisodeService()
        episode_id, _ = service.create_radio_episode("2099-01-03")

        def write_script(path, **kwargs):
            path_obj = tmp_path / "episodes" / str(episode_id) / "script.json"
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(json.dumps({"lines": [{"article_id": None, "text": "本文"}]}), encoding="utf-8")
            return 1

        with patch.object(radio_pipeline, "import_articles_by_source", return_value=(1, 0)), \
             patch.object(radio_pipeline, "summarize_articles", return_value=1), \
             patch.object(radio_pipeline, "generate_script", side_effect=write_script), \
             patch.object(radio_pipeline, "review_script", return_value={"revised": False, "review_count": 0}), \
             patch.object(radio_pipeline, "select_episode_categories", side_effect=RuntimeError("category failed")), \
             patch.object(radio_pipeline, "synthesize_episode", return_value=1), \
             patch.object(radio_pipeline, "build_episode", return_value={"audio_path": "episode.mp3"}):
            result = radio_pipeline.run_radio_pipeline(
                episode_id,
                episode_date="2099-01-03",
                default_episodes_dir=str(tmp_path / "episodes"),
            )

        assert result is not None
        assert service.get_episode(episode_id)["status"] == "completed"
