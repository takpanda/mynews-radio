import json

import pytest


@pytest.mark.parametrize("provider, model, base_url_env", [
    ("lm_studio", "lm-test-model", "LM_STUDIO_BASE_URL"),
    ("vllm", "vllm-test-model", "VLLM_BASE_URL"),
])
def test_run_daily_propagates_configured_provider_to_every_generation_stage(
    monkeypatch, tmp_path, provider, model, base_url_env,
):
    """cron entrypoint相当のrun_daily経由でもOllamaへフォールバックしない。"""
    from app.batch import radio_pipeline, run_daily
    from app.services.episode_service import EpisodeService

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LM_STUDIO_MODEL", "lm-test-model")
    monkeypatch.setenv("VLLM_MODEL", "vllm-test-model")
    monkeypatch.setenv(base_url_env, "http://llm.test")
    from app.config import get_settings
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-08-01", status="generating")
    calls = []

    def summarize(_path, **kwargs):
        calls.append(("summarize", kwargs))
        return 1

    def generate_script(path, **kwargs):
        calls.append(("generate_script", kwargs))
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"title": "test", "lines": [{"text": "line"}]}, output)
        return 1

    def review_script(*_args, **kwargs):
        calls.append(("review", kwargs))
        return {"revised": False, "review_count": 0}

    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _: (1, 0))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", summarize)
    monkeypatch.setattr(radio_pipeline, "generate_script", generate_script)
    monkeypatch.setattr(radio_pipeline, "review_script", review_script)
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(radio_pipeline, "build_episode", lambda _: {"audio_path": "episode.mp3"})
    monkeypatch.setattr(run_daily, "setup_daily_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {})
    monkeypatch.setattr(run_daily.EpisodeService, "create_radio_episode", lambda *_args, **_kwargs: (episode_id, 0))
    monkeypatch.setattr(run_daily, "_write_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_daily, "run_radio_pipeline", radio_pipeline.run_radio_pipeline)

    run_daily.main()

    assert [(stage, kwargs["llm_provider"], kwargs["llm_model"]) for stage, kwargs in calls] == [
        ("summarize", provider, model),
        ("generate_script", provider, model),
        ("review", provider, model),
    ]
