"""BEE-903: カテゴリ別女性MC設定・固定試聴・Fish S2 Pro解決のテスト。"""

import json
import wave

import pytest

from app.services import settings_service
from app.services.episode_category_service import EPISODE_CATEGORIES


def _voice_settings(**overrides):
    values = {
        "aivispeech_speaker_male": 1,
        "aivispeech_speaker_female": 2,
        "voicevox_speaker_male": 11,
        "voicevox_speaker_female": 22,
        "fishs2pro_voice_male": "male",
        "fishs2pro_voice_female": "morigawa",
    }
    values.update(overrides)
    return settings_service.validate_voice_settings(**values)


class TestCategoryFemaleVoiceSettings:
    def test_accepts_only_fixed_categories_and_allowlisted_voices(self):
        value = settings_service.validate_category_female_voices({
            "政治・行政": "female",
            "経済・金融": None,
        })
        assert value == {"政治・行政": "female", "経済・金融": None}

    @pytest.mark.parametrize(
        "value",
        [
            {"存在しないカテゴリ": "female"},
            {"政治・行政": "unknown-voice"},
            {"政治・行政": 123},
        ],
    )
    def test_rejects_unknown_category_or_voice(self, value):
        with pytest.raises(ValueError):
            settings_service.validate_category_female_voices(value)

    def test_round_trip_preserves_other_settings(self):
        settings_service.save_voice_settings(_voice_settings(
            fishs2pro_voice_female="morigawa",
        ))
        saved = settings_service.save_category_female_voices({"テック・IT": "female"})
        assert saved == {"テック・IT": "female"}
        assert settings_service.get_category_female_voices_or_default() == saved
        assert settings_service.get_voice_settings_or_default().fishs2pro_voice_female == "morigawa"

    def test_resolution_uses_first_matching_category_and_falls_back_when_unavailable(self):
        settings_service.save_voice_settings(_voice_settings())
        settings_service.save_category_female_voices({
            "政治・行政": "female",
            "経済・金融": "morigawa",
        })
        assert settings_service.resolve_category_female_voice(
            ["政治・行政", "経済・金融"], available_voices={"female", "morigawa"}
        ) == "female"
        assert settings_service.resolve_category_female_voice(
            ["政治・行政"], available_voices={"morigawa"}
        ) == "morigawa"


class TestCategoryFemaleVoiceApi:
    def test_get_returns_all_categories_and_fixed_candidates(self, client):
        response = client.get("/settings/voices/categories")
        assert response.status_code == 200
        data = response.json()
        assert data["categories"] == list(EPISODE_CATEGORIES)
        assert set(data["category_female_voices"]) == set(EPISODE_CATEGORIES)
        assert {item["value"] for item in data["voices"]} == {"female", "morigawa"}
        assert all(item["sample"]["url"].startswith("/settings/voices/categories/samples/") for item in data["voices"])
        assert "fishs2pro_base_url" not in json.dumps(data)

    def test_put_round_trip_and_rejects_invalid_input(self, client):
        response = client.put(
            "/settings/voices/categories",
            json={"category_female_voices": {"テック・IT": "female", "その他": None}},
        )
        assert response.status_code == 200
        assert response.json()["category_female_voices"]["テック・IT"] == "female"
        assert response.json()["category_female_voices"]["その他"] is None
        assert client.get("/settings/voices/categories").json()["category_female_voices"]["テック・IT"] == "female"

        invalid_voice = client.put(
            "/settings/voices/categories",
            json={"category_female_voices": {"テック・IT": "not-allowed"}},
        )
        assert invalid_voice.status_code == 422

        invalid_category = client.put(
            "/settings/voices/categories",
            json={"category_female_voices": {"unknown": "female"}},
        )
        assert invalid_category.status_code == 422

    def test_get_and_put_require_owner_session(self):
        from app.main import app
        from fastapi.testclient import TestClient

        unauthenticated = TestClient(app)
        assert unauthenticated.get("/settings/voices/categories").status_code in (401, 403)
        assert unauthenticated.put(
            "/settings/voices/categories",
            json={"category_female_voices": {"テック・IT": "female"}},
        ).status_code in (401, 403)

    def test_sample_requires_owner_and_serves_only_allowlisted_file(self, client, monkeypatch, tmp_path):
        from app.api import settings as settings_api

        sample = tmp_path / "female.wav"
        with wave.open(str(sample), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            wav.writeframes(b"\0\0")

        monkeypatch.setattr(
            settings_api,
            "_female_mc_sample_path",
            lambda voice_name: tmp_path / f"{voice_name}.wav",
        )
        response = client.get("/settings/voices/categories/samples/female")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        assert client.get("/settings/voices/categories/samples/not-allowed").status_code == 404

        from fastapi.testclient import TestClient
        from app.main import app

        assert TestClient(app).get("/settings/voices/categories/samples/female").status_code in (401, 403)


def test_fishs2pro_explicit_speakers_take_precedence_over_category_settings(monkeypatch, tmp_path):
    """既存契約どおり、パイプラインへの明示話者値は保存設定より優先する。"""
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService

    settings_service.save_voice_settings(_voice_settings())
    settings_service.save_category_female_voices({"テック・IT": "female"})
    episode_id, _ = EpisodeService().create_radio_episode("2099-04-01")
    captured = {}

    def write_script(path, **_kwargs):
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"lines": [{"article_id": None, "text": "本文"}]}, output)
        return 1

    def capture_synthesis(*_args, **kwargs):
        captured.update(kwargs)
        return 1

    def unexpected_category_resolution(*_args, **_kwargs):
        raise AssertionError("explicit Fish S2 Pro speakers must skip category resolution")

    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _source: (1, 0))
    monkeypatch.setattr(radio_pipeline, "summarize_articles", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(radio_pipeline, "generate_script", write_script)
    monkeypatch.setattr(
        radio_pipeline,
        "review_script",
        lambda *_args, **_kwargs: {"revised": False, "review_count": 0},
    )
    monkeypatch.setattr(radio_pipeline, "select_episode_categories", lambda *_args: ["テック・IT"])
    monkeypatch.setattr(radio_pipeline, "synthesize_episode", capture_synthesis)
    monkeypatch.setattr(
        radio_pipeline,
        "build_episode",
        lambda *_args, **_kwargs: {"audio_path": "episode.mp3"},
    )
    monkeypatch.setattr(
        radio_pipeline,
        "_resolve_fishs2pro_category_female_voice",
        unexpected_category_resolution,
    )

    result = radio_pipeline.run_radio_pipeline(
        episode_id,
        episode_date="2099-04-01",
        tts_engine="fishs2pro",
        tts_base_url="http://explicit-fish.test",
        tts_speaker_male="explicit-male",
        tts_speaker_female="explicit-female",
        default_episodes_dir=str(tmp_path),
    )

    assert result is not None
    assert captured["tts_engine"] == "fishs2pro"
    assert captured["speaker_male"] == "explicit-male"
    assert captured["speaker_female"] == "explicit-female"
