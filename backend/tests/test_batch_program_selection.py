import json
from contextlib import nullcontext

import pytest

from app.batch import run_daily
from app.programs.profiles import ProgramProfile, ProgramCastMember, ProgramSegment
from app.services.generation_control import JobClaim


@pytest.fixture
def profile():
    return ProgramProfile(
        id="radio_news_neighbor",
        name="ニュースのとなり",
        kind="radio",
        cast=(ProgramCastMember(key="male", name="MC"),),
        segments=(ProgramSegment(id="intro", kind="intro", order=0, min_lines=1, max_lines=2),),
    )


def _run_main(monkeypatch, enqueue_calls):
    monkeypatch.setattr(run_daily, "setup_daily_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_daily, "get_db_connection", lambda: nullcontext(object()))
    monkeypatch.setattr(run_daily, "ensure_generation_system_owner", lambda _conn: 1)
    monkeypatch.setattr(run_daily, "enqueue_job", lambda *args, **kwargs: (
        enqueue_calls.append((args, kwargs)) or JobClaim(1, None, status="waiting")
    ))


def test_batch_program_id_is_resolved_and_frozen_on_episode_reservation(monkeypatch, profile):
    enqueue_calls = []
    resolved_ids = []

    def resolve(request):
        resolved_ids.append(request.program_id)
        return profile

    monkeypatch.setenv("BATCH_PROGRAM_ID", "radio_news_neighbor")
    monkeypatch.setenv("BATCH_NEWS_SOURCE", "yahoo_news")
    monkeypatch.setattr(
        "app.api.generate._resolve_program_profile", resolve,
    )
    _run_main(monkeypatch, enqueue_calls)

    run_daily.main()

    args, kwargs = enqueue_calls[0]
    assert resolved_ids == ["radio_news_neighbor"]
    assert args[3]["program_id"] == "radio_news_neighbor"
    assert kwargs["program_id"] == profile.id
    assert json.loads(kwargs["program_snapshot"])["id"] == profile.id


def test_batch_program_id_resolution_failure_does_not_enqueue_or_fallback(monkeypatch):
    enqueue_calls = []
    error = ValueError("invalid program id")

    def fail(_request):
        raise error

    monkeypatch.setenv("BATCH_PROGRAM_ID", "123")
    monkeypatch.setattr("app.api.generate._resolve_program_profile", fail)
    _run_main(monkeypatch, enqueue_calls)

    with pytest.raises(ValueError, match="invalid program id"):
        run_daily.main()

    assert enqueue_calls == []


def test_batch_without_program_id_keeps_legacy_payload_and_pipeline_source(monkeypatch):
    enqueue_calls = []
    monkeypatch.delenv("BATCH_PROGRAM_ID", raising=False)
    monkeypatch.setenv("BATCH_DATE", "2099-10-01")
    monkeypatch.setenv("BATCH_NEWS_SOURCE", "yahoo_news")
    _run_main(monkeypatch, enqueue_calls)

    run_daily.main()

    args, kwargs = enqueue_calls[0]
    assert args[3] == {
        "date": "2099-10-01",
        "news_source": "yahoo_news",
        "tts_engine": run_daily.get_settings().batch_default_tts_engine,
    }
    assert kwargs["program_id"] is None
    assert kwargs["program_snapshot"] is None

    monkeypatch.setattr(run_daily.EpisodeService, "get_episode", lambda *_args: {"seq": 0})
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {})
    monkeypatch.setattr(run_daily, "_write_manifest", lambda **_kwargs: None)
    pipeline_calls = []

    def run_pipeline(*_args, **kwargs):
        pipeline_calls.append(kwargs)
        return run_daily.PipelineResult.NO_CONTENT

    monkeypatch.setattr(run_daily, "run_radio_pipeline", run_pipeline)
    assert run_daily.run_daily_job({
        "episode_id": 42,
        "payload": json.dumps(args[3]),
    }) is True
    assert pipeline_calls[0]["news_source"] == "yahoo_news"
    assert pipeline_calls[0]["program_profile"] is None


def test_batch_program_id_uses_episode_snapshot_and_program_source(monkeypatch, profile):
    monkeypatch.setattr(run_daily.EpisodeService, "get_episode", lambda *_args: {"seq": 0})
    monkeypatch.setattr(run_daily, "cleanup_episodes", lambda: {})
    monkeypatch.setattr(run_daily, "_write_manifest", lambda **_kwargs: None)
    monkeypatch.setattr(
        "app.api.generate._episode_program_profile", lambda _episode_id: profile,
    )
    pipeline_calls = []

    def run_pipeline(*_args, **kwargs):
        pipeline_calls.append(kwargs)
        return run_daily.PipelineResult.NO_CONTENT

    monkeypatch.setattr(run_daily, "run_radio_pipeline", run_pipeline)

    assert run_daily.run_daily_job({
        "episode_id": 42,
        "payload": json.dumps({
            "date": "2099-10-02",
            "news_source": "yahoo_news",
            "program_id": profile.id,
        }),
    }) is True
    assert pipeline_calls[0]["news_source"] == "hatena_hotentry_all"
    assert pipeline_calls[0]["program_profile"] is profile
