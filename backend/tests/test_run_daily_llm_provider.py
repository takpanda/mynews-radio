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
    monkeypatch.setattr(radio_pipeline, "build_episode", lambda *_args, **_kwargs: {"audio_path": "episode.mp3"})
    monkeypatch.setattr(run_daily, "setup_daily_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {})
    monkeypatch.setattr(run_daily.EpisodeService, "create_radio_episode", lambda *_args, **_kwargs: (episode_id, 0))
    monkeypatch.setattr(run_daily, "_write_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_daily, "run_radio_pipeline", radio_pipeline.run_radio_pipeline)

    run_daily.run_daily_job({"episode_id": episode_id, "payload": '{"date":"2099-08-01"}'})

    assert [(stage, kwargs["llm_provider"], kwargs["llm_model"]) for stage, kwargs in calls] == [
        ("summarize", provider, model),
        ("generate_script", provider, model),
        ("review", provider, model),
    ]


def test_radio_pipeline_separates_summary_and_content_llm(monkeypatch, tmp_path):
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService
    from app.config import get_settings

    # `.env.example`相当: vLLM providerは指定されるが、モデルは未設定。
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "vllm")
    monkeypatch.delenv("SUMMARIZE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "content-model")
    monkeypatch.setenv("OLLAMA_MODEL", "summary-model")
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-08-02", status="generating")
    calls = []

    def summarize(_path, **kwargs):
        calls.append(("summarize", kwargs))
        return 1

    def generate_script(path, **kwargs):
        calls.append(("generate_script", kwargs))
        (tmp_path / str(episode_id)).mkdir(parents=True, exist_ok=True)
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
    monkeypatch.setattr(radio_pipeline, "build_episode", lambda *_args, **_kwargs: {"audio_path": "episode.mp3"})

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-08-02",
        default_episodes_dir=str(tmp_path),
        tts_base_url="http://tts",
        tts_speaker_male=1,
        tts_speaker_female=2,
    )

    assert result is not None
    assert [(stage, kwargs["llm_provider"], kwargs["llm_model"]) for stage, kwargs in calls] == [
        ("summarize", "ollama", "summary-model"),
        ("generate_script", "codex", "content-model"),
        ("review", "codex", "content-model"),
    ]


def test_env_example_vllm_without_model_resolves_to_executable_ollama(monkeypatch):
    from app.config import get_settings
    from app.services.llm_provider import (
        resolve_pipeline_llm_selection,
        validate_provider_model,
    )

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "vllm")
    monkeypatch.delenv("SUMMARIZE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.6:27b")
    get_settings.cache_clear()

    selection = resolve_pipeline_llm_selection()
    config = validate_provider_model(selection.summarize_provider, selection.summarize_model)

    assert selection.summarize_provider == "ollama"
    assert selection.summarize_model is None
    assert config.name == "ollama"
    assert config.model == "qwen3.6:27b"


def test_explicit_common_llm_arguments_override_phase_environment_defaults(monkeypatch):
    from app.config import get_settings
    from app.services.llm_provider import resolve_pipeline_llm_selection

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "vllm")
    monkeypatch.delenv("SUMMARIZE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "content-model")
    get_settings.cache_clear()

    selection = resolve_pipeline_llm_selection(
        llm_provider="ollama",
        llm_model="legacy-model",
    )

    assert selection.legacy_common is True
    assert (selection.summarize_provider, selection.summarize_model) == ("ollama", "legacy-model")
    assert (selection.content_provider, selection.content_model) == ("ollama", "legacy-model")


def test_radio_pipeline_explicit_common_arguments_apply_to_all_three_llm_calls(monkeypatch, tmp_path):
    from app.batch import radio_pipeline
    from app.config import get_settings
    from app.services.episode_service import EpisodeService

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "vllm")
    monkeypatch.delenv("SUMMARIZE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "content-model")
    monkeypatch.setenv("OLLAMA_MODEL", "legacy-model")
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-08-03", status="generating")
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
    monkeypatch.setattr(radio_pipeline, "build_episode", lambda *_args, **_kwargs: {"audio_path": "episode.mp3"})

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-08-03",
        default_episodes_dir=str(tmp_path),
        tts_base_url="http://tts",
        tts_speaker_male=1,
        tts_speaker_female=2,
        llm_provider="ollama",
        llm_model="legacy-model",
    )

    assert result is not None
    assert [(stage, kwargs["llm_provider"], kwargs["llm_model"]) for stage, kwargs in calls] == [
        ("summarize", "ollama", "legacy-model"),
        ("generate_script", "ollama", "legacy-model"),
        ("review", "ollama", "legacy-model"),
    ]


@pytest.mark.parametrize("unavailable_phase", ["summarize", "content"])
def test_phase_validation_failure_is_isolated(monkeypatch, tmp_path, unavailable_phase):
    from app.batch import radio_pipeline
    from app.config import get_settings
    from app.services.episode_service import EpisodeService
    from app.services.llm_provider import ProviderConfig

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SUMMARIZE_LLM_MODEL", "summary-model")
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "content-model")
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-08-04", status="generating")
    calls = []

    def validate(provider, model):
        if (unavailable_phase == "summarize" and provider == "ollama") or (
            unavailable_phase == "content" and provider == "codex"
        ):
            raise RuntimeError(f"{unavailable_phase} unavailable")
        return ProviderConfig(provider, "http://llm.test", model or "configured-model")

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

    monkeypatch.setattr("app.services.llm_provider.validate_provider_model", validate)
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _: (1, 0))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", summarize)
    monkeypatch.setattr(radio_pipeline, "generate_script", generate_script)
    monkeypatch.setattr(radio_pipeline, "review_script", review_script)
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(radio_pipeline, "build_episode", lambda *_args, **_kwargs: {"audio_path": "episode.mp3"})

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-08-04",
        default_episodes_dir=str(tmp_path),
        tts_base_url="http://tts",
        tts_speaker_male=1,
        tts_speaker_female=2,
    )

    if unavailable_phase == "summarize":
        assert result is not None
        assert [stage for stage, _kwargs in calls] == ["generate_script", "review"]
        assert all(kwargs["llm_provider"] == "codex" for _stage, kwargs in calls)
    else:
        assert result is None
        assert [stage for stage, _kwargs in calls] == ["summarize"]
        assert calls[0][1]["llm_provider"] == "ollama"
    get_settings.cache_clear()
