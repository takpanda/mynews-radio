import json
import sqlite3


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

    def test_invalid_llm_response_falls_back_to_empty(self, monkeypatch, tmp_path):
        from app.services.episode_category_service import select_episode_categories

        script = tmp_path / "script.json"
        summaries = tmp_path / "summaries.json"
        script.write_text(json.dumps({"lines": [{"text": "AIのニュース"}]}), encoding="utf-8")
        summaries.write_text("[]", encoding="utf-8")

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def generate_json(self, prompt): return {"categories": ["不正カテゴリ", "テック・IT", "テック・IT", "AI・先端技術", "経済・金融", "政治・行政"]}

        assert select_episode_categories(str(script), str(summaries), client_factory=FakeClient) == [
            "テック・IT", "AI・先端技術", "経済・金融"
        ]
