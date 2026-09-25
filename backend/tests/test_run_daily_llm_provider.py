import importlib
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


def test_radio_pipeline_records_phase_provider_and_model_in_llm_call_logs(monkeypatch, tmp_path):
    """正常系パイプラインの全LLM段階が監査ログへ解決値を残す。"""
    from app.batch import radio_pipeline
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService
    from app.services.llm_call_log_service import record_llm_call, set_llm_context
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "summary-model")
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "content-model")
    get_settings.cache_clear()

    episode_id = EpisodeService().create_episode("2099-08-03", status="generating")
    episodes_dir = tmp_path / "episodes"
    output_dir = episodes_dir / str(episode_id)
    calls = []

    class FakeClient:
        def __init__(self, provider, model):
            self._provider = provider
            self._model = model

    def log(provider, model, phase):
        client = FakeClient(provider, model)
        set_llm_context(client, phase=phase, episode_id=episode_id)
        record_llm_call(client, attempt=1, status="success", prompt_text=phase)

    def summarize(_path, **kwargs):
        calls.append(("summarize", kwargs))
        log(kwargs["llm_provider"], kwargs["llm_model"], "summarize")
        return 1

    def generate_script(path, **kwargs):
        calls.append(("generate_script", kwargs))
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"title": "test", "lines": [{"text": "line"}]}, output)
        log(kwargs["llm_provider"], kwargs["llm_model"], "arc")
        log(kwargs["llm_provider"], kwargs["llm_model"], "script")
        return 1

    def review_script(*_args, **kwargs):
        calls.append(("review", kwargs))
        log(kwargs["llm_provider"], kwargs["llm_model"], "review")
        log(kwargs["llm_provider"], kwargs["llm_model"], "correction")
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
        default_episodes_dir=str(episodes_dir),
        tts_base_url="http://tts",
        tts_speaker_male=1,
        tts_speaker_female=2,
    )

    assert result is not None
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT phase, provider, model, status FROM llm_call_logs "
            "WHERE episode_id = ? ORDER BY id",
            (episode_id,),
        ).fetchall()
    phase_rows = [row for row in rows if row["phase"] in {"summarize", "arc", "script", "review", "correction"}]
    assert [(row["phase"], row["provider"], row["model"], row["status"]) for row in phase_rows] == [
        ("summarize", "ollama", "summary-model", "success"),
        ("arc", "codex", "content-model", "success"),
        ("script", "codex", "content-model", "success"),
        ("review", "codex", "content-model", "success"),
        ("correction", "codex", "content-model", "success"),
    ]


def test_generation_stages_set_context_on_clients_created_by_provider_factory(monkeypatch, tmp_path):
    """実処理関数の create_llm_client 経由で phase context が設定される。"""
    summary_module = importlib.import_module("app.batch.summarize_articles")
    script_module = importlib.import_module("app.batch.generate_script")
    review_module = importlib.import_module("app.batch.review_script")
    article_service_module = importlib.import_module("app.services.article_service")

    contexts = []

    class FakeClient:
        def __init__(self, responses):
            self.responses = iter(responses)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def generate_json(self, _prompt):
            return next(self.responses)

    def spy_context(module_name, original):
        def _set_context(client, **kwargs):
            contexts.append((module_name, kwargs["phase"], kwargs["episode_id"]))
            original(client, **kwargs)

        return _set_context

    for name, module in (
        ("summarize", summary_module),
        ("arc/script", script_module),
        ("review", review_module),
    ):
        monkeypatch.setattr(module, "set_llm_context", spy_context(name, module.set_llm_context))

    article = {
        "id": 1,
        "title": "article",
        "source": "test",
        "url": "https://example.test/article",
        "published_at": "2099-08-04T00:00:00Z",
        "text": "本文" * 100,
    }
    monkeypatch.setattr(article_service_module.ArticleService, "fetch_new_articles", lambda self: [article])
    monkeypatch.setattr(
        summary_module,
        "create_llm_client",
        lambda *_args: FakeClient([{"summary": "summary", "category": "general", "importance_score": 4}]),
    )
    summary_path = tmp_path / "episodes" / "123" / "summaries.json"
    assert summary_module.summarize_articles(
        str(summary_path), llm_provider="ollama", llm_model="summary-model"
    ) == 1

    monkeypatch.setattr(
        article_service_module.ArticleService,
        "fetch_summaries_for_script",
        lambda self, **_kwargs: [{
            "id": 1,
            "title": "article",
            "url": "https://example.test/article",
            "summary": "summary",
            "category": "general",
            "importance_score": 4,
        }],
    )
    monkeypatch.setenv("SCRIPT_LINT_RETRIES", "1")
    monkeypatch.setattr(
        script_module,
        "create_llm_client",
        lambda *_args: FakeClient([
            {"theme": "technology", "article_order": [1], "discussion_article_id": 1},
            {"title": "test", "lines": [{"speaker": "male", "section": "news", "text": "line", "article_id": 1}]},
        ]),
    )
    script_path = tmp_path / "episodes" / "123" / "script.json"
    assert script_module.generate_script(
        str(script_path), llm_provider="codex", llm_model="content-model"
    ) == 2

    source_path = tmp_path / "episodes" / "123" / "review-source.json"
    source_path.write_text(json.dumps({"title": "test", "lines": [{"speaker": "male", "text": "line"}]}), encoding="utf-8")
    monkeypatch.setattr(
        review_module,
        "create_llm_client",
        lambda *_args: FakeClient(
            [{"overall_score": 5, "issues": []}] * 5
            + [{"lines": [{"speaker": "male", "section": "news", "text": "line"}], "revision_summary": ""}]
        ),
    )
    review_module.review_script(
        str(source_path), str(tmp_path / "episodes" / "123" / "review"),
        llm_provider="codex", llm_model="content-model",
    )

    assert ("summarize", "summarize", 123) in contexts
    assert ("arc/script", "arc", 123) in contexts
    assert ("arc/script", "script", 123) in contexts
    assert ("review", "review", 123) in contexts
    assert ("review", "correction", 123) in contexts


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


def test_explicit_legacy_common_selection_overrides_phase_environment(monkeypatch):
    """明示された旧共通指定はフェーズ別環境変数より優先する。"""
    from app.config import get_settings
    from app.services.llm_provider import resolve_pipeline_llm_selection

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SUMMARIZE_LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "summary-model")
    monkeypatch.setenv("CONTENT_LLM_PROVIDER", "codex")
    get_settings.cache_clear()

    selection = resolve_pipeline_llm_selection(
        llm_provider="ollama",
        llm_model="legacy-model",
    )

    assert selection.legacy_common is True
    assert (selection.summarize_provider, selection.summarize_model) == ("ollama", "legacy-model")
    assert (selection.content_provider, selection.content_model) == ("ollama", "legacy-model")


def test_review_required_daily_result_is_successful_and_manifested(monkeypatch, tmp_path):
    from app.batch import radio_pipeline, run_daily
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-08-03", status="generating")
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {})
    monkeypatch.setattr(run_daily, "run_radio_pipeline", lambda *_args, **_kwargs: radio_pipeline.PipelineResult.REVIEW_REQUIRED)
    manifest = {}
    monkeypatch.setattr(run_daily, "_write_manifest", lambda **kwargs: manifest.update(kwargs))

    success = run_daily.run_daily_job({"episode_id": episode_id, "payload": '{"date":"2099-08-03"}'})

    assert success is True
    assert manifest == {"status": "awaiting_review"}
