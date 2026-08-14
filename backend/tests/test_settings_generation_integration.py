from datetime import datetime, timezone
import json
import os

from app.services.article_service import ArticleService
from app.services.settings_service import validate_settings


def _insert_summary(conn, title, category, score):
    conn.execute(
        "INSERT INTO articles (title, source, url, text, summary, category, importance_score, "
        "difficulty, status, published_at) VALUES (?, ?, ?, '', ?, ?, ?, 1, 'summarized', ?)",
        (title, "test", f"https://example.test/{title}", title, category, score,
         datetime.now(timezone.utc).isoformat()),
    )


def test_saved_theme_contract_changes_selected_articles_and_preserves_safety_valve(monkeypatch):
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        _insert_summary(conn, "business", "business", 3)
        _insert_summary(conn, "sports", "sports", 3)
        _insert_summary(conn, "critical-technology", "technology", 5)
        _insert_summary(conn, "excluded-technology", "technology", 3)

    service = ArticleService()
    default = service.fetch_summaries_for_script(10, 2, source="test")
    assert {item["category"] for item in default} == {"business", "sports", "technology"}

    profile = validate_settings(["business"], ["sports", "technology"], "normal")
    selected = service.fetch_summaries_for_script(
        **profile.generation_params(), source="test"
    )
    assert selected[0]["category"] == "business"
    assert "sports" not in {item["category"] for item in selected}
    assert "critical-technology" in {item["title"] for item in selected}
    assert "excluded-technology" not in {item["title"] for item in selected}


def test_applied_settings_are_kept_in_episode_metadata(tmp_path):
    from app.api.episodes import _enrich_episode

    episode_dir = tmp_path / "episodes" / "1"
    episode_dir.mkdir(parents=True)
    (episode_dir / "metadata.json").write_text(
        json.dumps({
            "duration_seconds": 180.0,
            "applied_settings": {
                "priority_themes": ["business"],
                "excluded_themes": ["sports"],
                "duration_preset": "short",
            },
        }),
        encoding="utf-8",
    )

    episode = {"id": 1, "date": "2099-01-01"}
    _enrich_episode(episode)

    assert episode["applied_settings"] == {
        "priority_themes": ["business"],
        "excluded_themes": ["sports"],
        "duration_preset": "short",
    }


def test_radio_pipeline_persists_applied_settings(monkeypatch, tmp_path):
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService
    from app.services.settings_service import validate_settings

    episode_id = EpisodeService().create_episode("2099-02-01", status="generating")
    episode_dir = tmp_path / str(episode_id)
    profile = validate_settings(["business"], ["sports"], "short")

    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _: (1, 0))
    llm_calls = []
    monkeypatch.setattr(radio_pipeline, "summarize_articles", lambda *_args, **kwargs: (llm_calls.append(kwargs) or 1))

    def write_script(path, **kwargs):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"title": "test", "date": "2099-02-01", "lines": [{"text": "line"}]}, f)
        return 1

    def generate_with_capture(path, **kwargs):
        llm_calls.append(kwargs)
        return write_script(path, **kwargs)

    monkeypatch.setattr(radio_pipeline, "generate_script", generate_with_capture)
    monkeypatch.setattr(radio_pipeline, "review_script", lambda *_args, **kwargs: (llm_calls.append(kwargs) or {"revised": False, "review_count": 0}))
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        radio_pipeline,
        "build_episode",
        lambda *_args, **_kwargs: {"audio_path": "episode.mp3", "duration_seconds": 90.0},
    )

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-02-01",
        program_settings=profile,
        default_episodes_dir=str(tmp_path),
        tts_base_url="http://tts",
        tts_speaker_male=1,
        tts_speaker_female=2,
    )

    expected = profile.to_dict()
    assert result["applied_settings"] == expected
    assert [(call["llm_provider"], call["llm_model"]) for call in llm_calls] == [
        ("ollama", "qwen3.6:35b"),
        ("ollama", "qwen3.6:35b"),
        ("ollama", "qwen3.6:35b"),
    ]
    with open(episode_dir / "metadata.json", encoding="utf-8") as f:
        assert json.load(f)["applied_settings"] == expected


def test_episode_list_and_detail_expose_applied_settings_only_when_present(client):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    configured_id = service.create_episode("2099-02-02", audio_path="episode.mp3", status="completed")
    default_id = service.create_episode("2099-02-03", audio_path="episode.mp3", status="completed")
    episodes_dir = os.environ["EPISODES_DIR"]
    configured_dir = os.path.join(episodes_dir, str(configured_id))
    default_dir = os.path.join(episodes_dir, str(default_id))
    os.makedirs(configured_dir)
    os.makedirs(default_dir)
    applied = {
        "priority_themes": ["business"],
        "excluded_themes": ["sports"],
        "duration_preset": "short",
    }
    with open(os.path.join(configured_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"duration_seconds": 90.0, "applied_settings": applied}, f)
    with open(os.path.join(default_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"duration_seconds": 90.0}, f)

    listed = client.get("/episodes?include_failed=true")
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()}
    assert by_id[configured_id]["applied_settings"] == applied
    assert "applied_settings" not in by_id[default_id]

    detail = client.get(f"/episodes/{configured_id}")
    assert detail.status_code == 200
    assert detail.json()["applied_settings"] == applied
    default_detail = client.get(f"/episodes/{default_id}")
    assert default_detail.status_code == 200
    assert "applied_settings" not in default_detail.json()
