import json
import wave
from types import SimpleNamespace
from unittest.mock import patch


def _settings():
    return SimpleNamespace(
        default_tts_engine="aivispeech",
        fishs2pro_base_url="http://fish.test",
        fishs2pro_voice_male="male",
        fishs2pro_voice_female="morigawa",
        aivispeech_base_url="http://aivispeech.test",
        voicevox_base_url="http://voicevox.test",
        aivispeech_speaker_male=10,
        aivispeech_speaker_female=20,
        voicevox_speaker_male=11,
        voicevox_speaker_female=2,
        jingle_transition_path="",
    )


def test_fishs2pro_episode_uses_male_and_female_and_44100hz(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [
            {"text": "男性本文", "speaker": "male"},
            {"text": "女性本文", "speaker": "female"},
        ]}),
        encoding="utf-8",
    )
    calls = []

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            assert base_url == "http://fish.test"
            assert voice_male == "male"
            assert voice_female == "morigawa"

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            calls.append((text, speaker, delivery))
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\0\0" * 10)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient):
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 2

    assert [call[1] for call in calls] == ["male", "female"]
    with wave.open(str(episode_dir / "lines" / "001.wav"), "rb") as wav:
        assert wav.getframerate() == 44100


def test_fishs2pro_episode_uses_saved_voices_when_speakers_are_omitted(tmp_path):
    """直接呼び出しでも user_settings のFish S2 Pro音声をクライアントへ渡す。"""
    from app.batch.synthesize_voicevox import synthesize_episode
    from app.services import settings_service

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [{"text": "本文", "speaker": "female"}]}),
        encoding="utf-8",
    )
    settings_service.save_voice_settings(settings_service.validate_voice_settings(
        aivispeech_speaker_male=1,
        aivispeech_speaker_female=2,
        voicevox_speaker_male=11,
        voicevox_speaker_female=22,
        fishs2pro_voice_male="saved-male",
        fishs2pro_voice_female="saved-female",
    ))
    client_voices = {}

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            client_voices.update(male=voice_male, female=voice_female)

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\0\0" * 10)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient):
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 1

    assert client_voices == {"male": "saved-male", "female": "saved-female"}


def test_fishs2pro_episode_keeps_explicit_speakers_over_saved_voices(tmp_path):
    """明示された話者は保存値より優先し、既存の呼び出し契約を維持する。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [{"text": "本文", "speaker": "male"}]}),
        encoding="utf-8",
    )
    client_voices = {}

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            client_voices.update(male=voice_male, female=voice_female)

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\0\0" * 10)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.resolve_tts_speakers",
               side_effect=AssertionError("explicit speakers must not read saved settings")), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient):
        assert synthesize_episode(
            str(episode_dir),
            tts_engine="fishs2pro",
            speaker_male="explicit-male",
            speaker_female="explicit-female",
        ) == 1

    assert client_voices == {"male": "explicit-male", "female": "explicit-female"}


def test_fishs2pro_female_audio_is_not_volume_normalized(tmp_path):
    """Fish S2 Pro の女性MC音声には専用の平均音量正規化を適用しない（BEE-687回帰テスト）。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [
            {"text": "男性本文", "speaker": "male"},
            {"text": "女性本文", "speaker": "female"},
        ]}),
        encoding="utf-8",
    )

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\0\0" * 10)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient), \
         patch("app.batch.synthesize_voicevox.normalize_mean_volume", create=True) as mock_normalize:
        # 音量正規化用の関数を一切呼ばなくても、男女とも合成が成功すること。
        # 旧実装は本モジュールへ直接importした normalize_mean_volume を呼び出していたため、
        # 同じ呼び出し位置をモックして退行（呼び出しの復活）を検出できるようにする。
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 2

    mock_normalize.assert_not_called()
    assert (episode_dir / "lines" / "001.wav").exists()
    assert (episode_dir / "lines" / "002.wav").exists()


def test_fishs2pro_normalizes_transition_before_combining(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode
    from app.services.ffmpeg_service import combine_wav_files

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [{"text": "遷移後本文", "speaker": "male", "section": "transition"}]}),
        encoding="utf-8",
    )

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\0\0" * 10)
            return True

        def close(self):
            pass

    def fake_convert(source, destination, sample_rate):
        with wave.open(destination, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\0\0" * 10)
        return True

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient), \
         patch("app.batch.synthesize_voicevox.convert_to_wav", side_effect=fake_convert):
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 1

    wav_files = sorted((episode_dir / "lines").glob("*.wav"))
    combined = episode_dir / "combined.wav"
    combine_wav_files([str(path) for path in wav_files], str(combined))
    with wave.open(str(combined), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (44100, 1, 2)


def test_unset_generate_and_resynthesize_requests_use_configured_default(tmp_path):
    from app.api import generate as generate_api
    from app.batch.radio_pipeline import _determine_tts_config
    from app.services.episode_service import EpisodeService

    fish_settings = _settings()
    fish_settings.default_tts_engine = "fishs2pro"
    assert generate_api.GenerateRequest(date="2099-01-01").tts_engine is None
    assert generate_api.SynthesizeRequest().tts_engine is None

    with patch.object(generate_api, "get_settings", return_value=fish_settings), \
         patch("app.batch.radio_pipeline.get_settings", return_value=fish_settings):
        assert _determine_tts_config(None)["tts_engine"] == "fishs2pro"

        episode_id, _ = EpisodeService().create_radio_episode("2099-01-01")
        episode_dir = tmp_path / str(episode_id)
        (episode_dir / "lines").mkdir(parents=True)
        (episode_dir / "script.json").write_text(json.dumps({"lines": []}), encoding="utf-8")

        with patch.object(generate_api, "DEFAULT_EPISODES_DIR", str(tmp_path)), \
             patch.object(generate_api, "synthesize_episode", return_value=1) as synthesize, \
             patch.object(generate_api, "build_episode", return_value={"audio_path": "episode.mp3"}):
            list(generate_api._stream_synthesize(episode_id, generate_api.SynthesizeRequest()))

    kwargs = synthesize.call_args.kwargs
    assert kwargs["base_url"] == "http://fish.test"
    assert kwargs["speaker_male"] == "male"
    assert kwargs["speaker_female"] == "morigawa"
    assert kwargs["tts_engine"] == "fishs2pro"


def test_unset_generate_request_passes_configured_default_to_pipeline():
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    fish_settings = _settings()
    fish_settings.default_tts_engine = "fishs2pro"
    episode_id, _ = EpisodeService().create_radio_episode("2099-01-02")

    with patch.object(generate_api, "get_settings", return_value=fish_settings), \
         patch.object(generate_api, "run_radio_pipeline", return_value={"audio_path": "episode.mp3"}) as pipeline:
        generate_api._run_generation(episode_id, generate_api.GenerateRequest(date="2099-01-02"))

    assert pipeline.call_args.kwargs["tts_engine"] == "fishs2pro"


def test_unset_generate_request_keeps_aivispeech_default_with_real_settings(tmp_path):
    """実設定(default_tts_engine=aivispeech)で、未指定のPOST /generateはFish S2 Proへ切り替わらない(BEE-619 review対応)。"""
    from app.api import generate as generate_api
    from app.config import Settings
    from app.services.episode_service import EpisodeService

    assert Settings().default_tts_engine == "aivispeech"
    episode_id, _ = EpisodeService().create_radio_episode("2099-01-03")

    with patch.object(generate_api, "run_radio_pipeline", return_value={"audio_path": "episode.mp3"}) as pipeline:
        generate_api._run_generation(episode_id, generate_api.GenerateRequest(date="2099-01-03"))

    assert pipeline.call_args.kwargs["tts_engine"] == "aivispeech"


def test_unset_resynthesize_request_keeps_aivispeech_default_with_real_settings(tmp_path):
    """実設定で、未指定の再合成APIはFish S2 Proへ切り替わらない(BEE-619 review対応)。"""
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    episode_id, _ = EpisodeService().create_radio_episode("2099-01-04")
    episode_dir = tmp_path / str(episode_id)
    (episode_dir / "lines").mkdir(parents=True)
    (episode_dir / "script.json").write_text(json.dumps({"lines": []}), encoding="utf-8")

    with patch.object(generate_api, "DEFAULT_EPISODES_DIR", str(tmp_path)), \
         patch.object(generate_api, "synthesize_episode", return_value=1) as synthesize, \
         patch.object(generate_api, "build_episode", return_value={"audio_path": "episode.mp3"}):
        list(generate_api._stream_synthesize(episode_id, generate_api.SynthesizeRequest()))

    assert synthesize.call_args.kwargs["tts_engine"] == "aivispeech"


def test_determine_tts_config_for_fishs2pro():
    from app.batch import radio_pipeline

    with patch.object(radio_pipeline, "get_settings", return_value=_settings()):
        config = radio_pipeline._determine_tts_config("fishs2pro")

    assert config == {
        "tts_engine": "fishs2pro",
        "base_url": "http://fish.test",
        "speaker_male": "male",
        "speaker_female": "morigawa",
    }


def test_health_check_fishs2pro_uses_fish_client():
    from app.batch import health_check

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            assert base_url == "http://fish.test"
            assert voice_male == "male"
            assert voice_female == "morigawa"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def health_check(self):
            return {"status": "ok", "voices": ["male", "morigawa"]}

    with patch.object(health_check, "FishS2ProClient", FakeFishClient), \
         patch.object(health_check, "get_settings", return_value=_settings()):
        result = health_check.health_check_tts("http://fish.test", "fishs2pro")

    assert result["service"] == "fishs2pro"
    assert result["status"] == "ok"


def test_health_check_fishs2pro_reports_error_when_configured_voice_missing():
    from app.batch import health_check

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def health_check(self):
            return {"status": "error", "detail": "health response does not provide required voices: ['male', 'morigawa']"}

    with patch.object(health_check, "FishS2ProClient", FakeFishClient), \
         patch.object(health_check, "get_settings", return_value=_settings()):
        result = health_check.health_check_tts("http://fish.test", "fishs2pro")

    assert result["status"] == "error"
