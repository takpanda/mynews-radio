"""BEE-708: Fish S2 Pro の行単位の合成失敗に対する再試行動作のテスト。"""
import json
import logging
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


def _write_wav(output_path: str) -> None:
    with wave.open(output_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\0\0" * 10)


def test_fishs2pro_first_attempt_success_does_not_retry(tmp_path):
    """初回の合成が成功した行は再試行されないこと。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [{"text": "本文", "speaker": "male"}]}),
        encoding="utf-8",
    )
    call_count = {"n": 0}

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            call_count["n"] += 1
            _write_wav(output_path)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient), \
         patch("app.batch.synthesize_voicevox.time.sleep") as mock_sleep:
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 1

    assert call_count["n"] == 1
    mock_sleep.assert_not_called()


def test_fishs2pro_retries_failed_line_and_saves_one_file_on_success(tmp_path, caplog):
    """初回失敗・再試行で成功した場合、同じ行だけが再試行され音声ファイルが1件保存されること。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [
            {"text": "1行目", "speaker": "male"},
            {"text": "2行目", "speaker": "female"},
        ]}),
        encoding="utf-8",
    )
    attempts = {"line1": 0, "line2": 0}

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            if text == "1行目":
                attempts["line1"] += 1
                if attempts["line1"] == 1:
                    return False  # 初回失敗
            else:
                attempts["line2"] += 1
            _write_wav(output_path)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient), \
         patch("app.batch.synthesize_voicevox.time.sleep") as mock_sleep, \
         caplog.at_level(logging.INFO, logger="app.batch.synthesize_voicevox"):
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 2

    assert attempts["line1"] == 2  # 初回失敗 + 再試行1回で成功
    assert attempts["line2"] == 1  # 初回成功行は再試行されない
    mock_sleep.assert_called_once()
    assert sorted(p.name for p in (episode_dir / "lines").glob("*.wav")) == ["001.wav", "002.wav"]
    assert any(
        "succeeded on retry" in r.message and "Line 1" in r.message for r in caplog.records
    )


def test_fishs2pro_gives_up_after_max_retries(tmp_path, caplog):
    """再試行上限まで失敗した場合、成功件数を過大に記録せず最終失敗をログに残すこと。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [
            {"text": "失敗行", "speaker": "male"},
            {"text": "成功行", "speaker": "female"},
        ]}),
        encoding="utf-8",
    )
    attempts = {"fail": 0}

    class FakeFishClient:
        def __init__(self, base_url, voice_male=None, voice_female=None):
            pass

        def synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            if text == "失敗行":
                attempts["fail"] += 1
                return False  # 常に失敗
            _write_wav(output_path)
            return True

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_settings()), \
         patch("app.batch.synthesize_voicevox.FishS2ProClient", FakeFishClient), \
         patch("app.batch.synthesize_voicevox.time.sleep") as mock_sleep, \
         caplog.at_level(logging.INFO, logger="app.batch.synthesize_voicevox"):
        assert synthesize_episode(str(episode_dir), tts_engine="fishs2pro") == 1

    assert attempts["fail"] == 3  # 初回 + 再試行2回（上限）
    assert mock_sleep.call_count == 2
    assert not (episode_dir / "lines" / "001.wav").exists()
    assert any("giving up" in r.message and "Line 1" in r.message for r in caplog.records)
