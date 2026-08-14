"""BEE-725: ボイス設定（AivisSpeech/VOICEVOX/Fish S2 Pro 男声・女声）のテスト。"""

import sqlite3
from pathlib import Path

import httpx
import pytest

from app.services import settings_service


def _config_defaults():
    from app.config import Settings

    settings = Settings()
    return {
        "aivispeech_speaker_male": settings.aivispeech_speaker_male,
        "aivispeech_speaker_female": settings.aivispeech_speaker_female,
        "voicevox_speaker_male": settings.voicevox_speaker_male,
        "voicevox_speaker_female": settings.voicevox_speaker_female,
        "fishs2pro_voice_male": settings.fishs2pro_voice_male,
        "fishs2pro_voice_female": settings.fishs2pro_voice_female,
    }


class TestValidateVoiceSettings:
    def test_accepts_valid_values(self):
        result = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1,
            aivispeech_speaker_female=2,
            voicevox_speaker_male=11,
            voicevox_speaker_female=22,
            fishs2pro_voice_male="male",
            fishs2pro_voice_female="morigawa",
        )
        assert result.to_dict() == {
            "aivispeech_speaker_male": 1,
            "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11,
            "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male",
            "fishs2pro_voice_female": "morigawa",
        }

    def test_rejects_non_integer_speaker_id(self):
        with pytest.raises(ValueError):
            settings_service.validate_voice_settings(
                aivispeech_speaker_male="1", aivispeech_speaker_female=2,
                voicevox_speaker_male=11, voicevox_speaker_female=22,
                fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
            )

    def test_rejects_bool_speaker_id(self):
        """isinstance(True, int) is True なので明示的に弾く必要がある."""
        with pytest.raises(ValueError):
            settings_service.validate_voice_settings(
                aivispeech_speaker_male=True, aivispeech_speaker_female=2,
                voicevox_speaker_male=11, voicevox_speaker_female=22,
                fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
            )

    def test_rejects_empty_fishs2pro_voice_name(self):
        with pytest.raises(ValueError):
            settings_service.validate_voice_settings(
                aivispeech_speaker_male=1, aivispeech_speaker_female=2,
                voicevox_speaker_male=11, voicevox_speaker_female=22,
                fishs2pro_voice_male="", fishs2pro_voice_female="morigawa",
            )

    def test_rejects_blank_fishs2pro_voice_name(self):
        with pytest.raises(ValueError):
            settings_service.validate_voice_settings(
                aivispeech_speaker_male=1, aivispeech_speaker_female=2,
                voicevox_speaker_male=11, voicevox_speaker_female=22,
                fishs2pro_voice_male="male", fishs2pro_voice_female="   ",
            )


class TestVoiceSettingsPersistence:
    def test_get_falls_back_to_config_defaults_when_unsaved(self):
        assert settings_service.get_voice_settings_or_default().to_dict() == _config_defaults()

    def test_get_falls_back_to_config_defaults_on_database_failure(self, monkeypatch):
        def broken_connection():
            raise sqlite3.OperationalError("database unavailable")

        monkeypatch.setattr(settings_service, "get_db_connection", broken_connection)
        assert settings_service.get_voice_settings_or_default().to_dict() == _config_defaults()

    def test_get_falls_back_when_columns_are_missing(self, monkeypatch, tmp_path):
        """既存DBに追加カラムが無い場合も、config.py既定値で生成を継続できる。"""
        db_path = tmp_path / "legacy.db"

        class FakeSettings:
            database_url = f"sqlite:///{db_path}"

        from app.db import connection
        monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
        with connection.get_db_connection() as conn:
            conn.execute(
                "CREATE TABLE user_settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
                "priority_themes TEXT NOT NULL, excluded_themes TEXT NOT NULL, "
                "duration_preset TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO user_settings (id, priority_themes, excluded_themes, duration_preset, updated_at) "
                "VALUES (1, '[]', '[]', 'normal', CURRENT_TIMESTAMP)"
            )

        assert settings_service.get_voice_settings_or_default().to_dict() == _config_defaults()

    def test_save_and_get_round_trip(self, monkeypatch, tmp_path):
        db_path = tmp_path / "voices.db"

        class FakeSettings:
            database_url = f"sqlite:///{db_path}"

        from app.db import connection
        monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
        schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
        with connection.get_db_connection() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

        value = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1, aivispeech_speaker_female=2,
            voicevox_speaker_male=11, voicevox_speaker_female=22,
            fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
        )
        settings_service.save_voice_settings(value)
        assert settings_service.get_voice_settings_or_default() == value

    def test_save_voice_settings_preserves_program_settings(self, monkeypatch, tmp_path):
        """ボイス設定の保存が既存の優先テーマ等の行を破壊しないこと。"""
        db_path = tmp_path / "combined.db"

        class FakeSettings:
            database_url = f"sqlite:///{db_path}"

        from app.db import connection
        monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
        schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
        with connection.get_db_connection() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

        program = settings_service.validate_settings(["technology"], [], "short")
        settings_service.save_settings(program)

        voice = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1, aivispeech_speaker_female=2,
            voicevox_speaker_male=11, voicevox_speaker_female=22,
            fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
        )
        settings_service.save_voice_settings(voice)

        assert settings_service.get_settings_or_default() == program
        assert settings_service.get_voice_settings_or_default() == voice

    def test_schema_can_be_applied_again_without_losing_voice_settings(self, monkeypatch, tmp_path):
        db_path = tmp_path / "reapply.db"

        class FakeSettings:
            database_url = f"sqlite:///{db_path}"

        from app.db import connection
        monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
        schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
        with connection.get_db_connection() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

        value = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1, aivispeech_speaker_female=2,
            voicevox_speaker_male=11, voicevox_speaker_female=22,
            fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
        )
        settings_service.save_voice_settings(value)
        with connection.get_db_connection() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
        assert settings_service.get_voice_settings_or_default() == value


class TestResolveTtsSpeakers:
    def test_maps_each_engine_to_its_own_fields(self):
        vs = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1, aivispeech_speaker_female=2,
            voicevox_speaker_male=11, voicevox_speaker_female=22,
            fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
        )
        assert settings_service.resolve_tts_speakers("aivispeech", vs) == (1, 2)
        assert settings_service.resolve_tts_speakers("voicevox", vs) == (11, 22)
        assert settings_service.resolve_tts_speakers("fishs2pro", vs) == ("male", "morigawa")

    def test_unknown_engine_falls_back_to_aivispeech_fields(self):
        vs = settings_service.validate_voice_settings(
            aivispeech_speaker_male=1, aivispeech_speaker_female=2,
            voicevox_speaker_male=11, voicevox_speaker_female=22,
            fishs2pro_voice_male="male", fishs2pro_voice_female="morigawa",
        )
        assert settings_service.resolve_tts_speakers("unknown", vs) == (1, 2)

    def test_defaults_to_get_voice_settings_or_default_when_not_supplied(self):
        assert settings_service.resolve_tts_speakers("voicevox") == (
            _config_defaults()["voicevox_speaker_male"],
            _config_defaults()["voicevox_speaker_female"],
        )


class TestVoiceSettingsApi:
    def test_get_returns_config_defaults_when_unsaved(self, client):
        resp = client.get("/settings/voices")
        assert resp.status_code == 200
        assert resp.json() == _config_defaults()

    def test_put_then_get_round_trip(self, client):
        payload = {
            "aivispeech_speaker_male": 1, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male", "fishs2pro_voice_female": "morigawa",
        }
        saved = client.put("/settings/voices", json=payload)
        assert saved.status_code == 200
        assert saved.json() == payload
        assert client.get("/settings/voices").json() == payload

    def test_put_rejects_string_speaker_id(self, client):
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": "not-a-number", "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male", "fishs2pro_voice_female": "morigawa",
        })
        assert resp.status_code == 422

    def test_put_rejects_bool_speaker_id(self, client):
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": True, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male", "fishs2pro_voice_female": "morigawa",
        })
        assert resp.status_code == 422

    def test_put_rejects_empty_fishs2pro_voice_name(self, client):
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": 1, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "", "fishs2pro_voice_female": "morigawa",
        })
        assert resp.status_code == 422

    def test_put_rejects_missing_field(self, client):
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": 1, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male",
        })
        assert resp.status_code == 422

    def test_put_rejects_unknown_field(self, client):
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": 1, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male", "fishs2pro_voice_female": "morigawa",
            "unknown": True,
        })
        assert resp.status_code == 422

    def test_put_save_failure_returns_503(self, client, monkeypatch):
        from app.api import settings as settings_api
        monkeypatch.setattr(
            settings_api, "save_voice_settings",
            lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
        )
        resp = client.put("/settings/voices", json={
            "aivispeech_speaker_male": 1, "aivispeech_speaker_female": 2,
            "voicevox_speaker_male": 11, "voicevox_speaker_female": 22,
            "fishs2pro_voice_male": "male", "fishs2pro_voice_female": "morigawa",
        })
        assert resp.status_code == 503

    def test_voices_requires_authentication(self):
        from app.main import app
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/settings/voices")
        assert response.status_code in (401, 403)


class TestVoiceOptionsApi:
    def test_returns_common_format_for_all_engines_on_success(self, client, monkeypatch):
        from app.api import settings as settings_api

        def fake_speakers(self):
            return [{"speaker_name": "阿井田 茂", "style_name": "ノーマル", "value": 1310138976}]

        def fake_voices(self):
            return ["male", "morigawa"]

        monkeypatch.setattr(settings_api.VoicevoxClient, "list_speakers", fake_speakers)
        monkeypatch.setattr(settings_api.VoicevoxClient, "close", lambda self: None)
        monkeypatch.setattr(settings_api.FishS2ProClient, "list_voices", fake_voices)
        monkeypatch.setattr(settings_api.FishS2ProClient, "close", lambda self: None)

        resp = client.get("/settings/voices/options")
        assert resp.status_code == 200
        data = resp.json()

        assert data["aivispeech"]["status"] == "ok"
        assert data["aivispeech"]["options"] == [{
            "display_name": "阿井田 茂 - ノーマル",
            "value": 1310138976,
            "speaker_name": "阿井田 茂",
            "style_name": "ノーマル",
        }]
        assert data["voicevox"]["status"] == "ok"
        assert data["fishs2pro"]["status"] == "ok"
        assert data["fishs2pro"]["options"] == [
            {"display_name": "male", "value": "male", "speaker_name": None, "style_name": None},
            {"display_name": "morigawa", "value": "morigawa", "speaker_name": None, "style_name": None},
        ]

    def test_one_engine_failure_does_not_fail_whole_response(self, client, monkeypatch):
        from app.api import settings as settings_api

        def fake_speakers(self):
            return [{"speaker_name": "s", "style_name": "st", "value": 1}]

        def broken_speakers(self):
            raise httpx.ConnectError("connection refused to internal host with secret token abc123")

        def fake_voices(self):
            return ["male"]

        calls = {"n": 0}

        def alternating_speakers(self):
            calls["n"] += 1
            return fake_speakers(self) if calls["n"] == 1 else broken_speakers(self)

        monkeypatch.setattr(settings_api.VoicevoxClient, "list_speakers", alternating_speakers)
        monkeypatch.setattr(settings_api.VoicevoxClient, "close", lambda self: None)
        monkeypatch.setattr(settings_api.FishS2ProClient, "list_voices", fake_voices)
        monkeypatch.setattr(settings_api.FishS2ProClient, "close", lambda self: None)

        resp = client.get("/settings/voices/options")
        assert resp.status_code == 200
        data = resp.json()

        assert data["aivispeech"]["status"] == "ok"
        assert data["voicevox"]["status"] == "error"
        assert data["voicevox"]["options"] == []
        # 例外メッセージ（接続先や機微情報を含みうる）が応答へそのまま漏れないこと。
        assert "secret" not in (data["voicevox"]["error"] or "")
        assert "token" not in (data["voicevox"]["error"] or "")
        assert data["fishs2pro"]["status"] == "ok"

    def test_options_requires_authentication(self):
        from app.main import app
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/settings/voices/options")
        assert response.status_code in (401, 403)
