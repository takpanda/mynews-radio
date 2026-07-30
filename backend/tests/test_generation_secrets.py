from pathlib import Path

import pytest


@pytest.mark.parametrize("engine, env_name, host", [
    ("voicevox", "VOICEVOX_BASE_URL", "tts.voicevox.internal:50021"),
    ("aivispeech", "AIVISPEECH_BASE_URL", "tts.aivispeech.internal:10101"),
])
def test_synthesis_sse_never_exposes_tts_connection_url(client, monkeypatch, tmp_path, engine, env_name, host):
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-07-01", status="generating")
    episode_dir = Path(tmp_path) / str(episode_id)
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text('{"lines": []}', encoding="utf-8")
    monkeypatch.setattr(generate_api, "DEFAULT_EPISODES_DIR", str(tmp_path))
    monkeypatch.setenv(env_name, f"http://user:password@{host}")
    generate_api.get_settings.cache_clear()
    monkeypatch.setattr(generate_api, "synthesize_episode", lambda *args, **kwargs: 0)

    payload = b"".join(generate_api._stream_synthesize(
        episode_id, generate_api.SynthesizeRequest(tts_engine=engine)
    )).decode()

    assert engine.lower() in payload.lower()
    assert host not in payload
    assert "user:password" not in payload
