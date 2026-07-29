from pathlib import Path


def test_synthesis_sse_never_exposes_tts_connection_url(client, monkeypatch, tmp_path):
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-07-01", status="generating")
    episode_dir = Path(tmp_path) / str(episode_id)
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text('{"lines": []}', encoding="utf-8")
    monkeypatch.setattr(generate_api, "DEFAULT_EPISODES_DIR", str(tmp_path))
    monkeypatch.setenv("VOICEVOX_BASE_URL", "http://user:password@tts.internal:50021")
    monkeypatch.setenv("AIVISPEECH_BASE_URL", "http://user:password@tts.internal:10101")
    generate_api.get_settings.cache_clear()
    monkeypatch.setattr(generate_api, "synthesize_episode", lambda *args, **kwargs: 0)

    payload = b"".join(generate_api._stream_synthesize(
        episode_id, generate_api.SynthesizeRequest(tts_engine="voicevox")
    )).decode()

    assert "VOICEVOX" in payload
    assert "tts.internal" not in payload
    assert "user:password" not in payload
