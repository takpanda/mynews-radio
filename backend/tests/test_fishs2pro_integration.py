import json
import wave
from types import SimpleNamespace
from unittest.mock import patch


def _settings():
    return SimpleNamespace(
        default_tts_engine="aivispeech",
        fishs2pro_base_url="http://fish.test",
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
        def __init__(self, base_url):
            assert base_url == "http://fish.test"

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


def test_determine_tts_config_for_fishs2pro():
    from app.batch import radio_pipeline

    with patch.object(radio_pipeline, "get_settings", return_value=_settings()):
        config = radio_pipeline._determine_tts_config("fishs2pro")

    assert config == {
        "tts_engine": "fishs2pro",
        "base_url": "http://fish.test",
        "speaker_male": None,
        "speaker_female": None,
    }


def test_health_check_fishs2pro_uses_fish_client():
    from app.batch import health_check

    class FakeFishClient:
        def __init__(self, base_url):
            assert base_url == "http://fish.test"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def health_check(self):
            return {"status": "ok", "voices": ["male", "female"]}

    with patch.object(health_check, "FishS2ProClient", FakeFishClient):
        result = health_check.health_check_tts("http://fish.test", "fishs2pro")

    assert result["service"] == "fishs2pro"
    assert result["status"] == "ok"
