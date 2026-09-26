import json
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db.connection import get_db_connection
from app.db.migration import migrate_program_profiles
from app.services.episode_service import EpisodeService


def _suppress_generation_worker(monkeypatch):
    original_start = threading.Thread.start

    def start_without_generation(thread):
        target = getattr(thread, "_target", None)
        if getattr(target, "__name__", "") == "_run_pipeline_with_audit":
            return None
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start_without_generation)


def _seed_program_profiles():
    with get_db_connection() as conn:
        migrate_program_profiles(conn)


def test_program_id_controls_radio_source_and_snapshot_is_immutable(client, monkeypatch):
    _seed_program_profiles()
    _suppress_generation_worker(monkeypatch)
    response = client.post(
        "/generate",
        json={
            "date": "2099-11-01",
            "program_id": "radio_news_neighbor",
            "news_source": "hatena_bookmark",
        },
    )

    assert response.status_code == 200
    episode_id = response.json()["episode_id"]
    service = EpisodeService()
    episode = service.get_episode(episode_id)
    snapshot = json.loads(episode["program_snapshot"])
    assert episode["program_id"] == "radio_news_neighbor"
    assert snapshot["id"] == "radio_news_neighbor"
    assert snapshot["name"] == "ニュースのとなり"

    with get_db_connection() as conn:
        changed = dict(snapshot, name="更新後の番組名")
        conn.execute(
            "UPDATE programs SET name = ?, definition = ? WHERE id = ?",
            (changed["name"], json.dumps(changed, ensure_ascii=False), snapshot["id"]),
        )

    assert service.get_episode(episode_id)["program_snapshot"] == episode["program_snapshot"]

    from app.api.generate import GenerateRequest, _run_generation

    with patch("app.api.generate.run_radio_pipeline", return_value={"audio_path": "ep.mp3"}) as pipeline:
        _run_generation(
            episode_id,
            GenerateRequest(
                date="2099-11-01",
                program_id="radio_news_neighbor",
                news_source="hatena_bookmark",
            ),
        )

    assert pipeline.call_args.kwargs["news_source"] == "hatena_hotentry_all"
    assert pipeline.call_args.kwargs["program_profile"].name == "ニュースのとなり"


def test_program_id_missing_or_inactive_returns_400_without_fallback(client, monkeypatch):
    _seed_program_profiles()
    _suppress_generation_worker(monkeypatch)
    missing = client.post(
        "/generate", json={"date": "2099-11-02", "program_id": "missing"}
    )
    assert missing.status_code == 400

    with get_db_connection() as conn:
        conn.execute("UPDATE programs SET is_active = 0 WHERE id = 'radio_news_neighbor'")
    inactive = client.post(
        "/generate",
        json={"date": "2099-11-03", "program_id": "radio_news_neighbor"},
    )
    assert inactive.status_code == 400


@pytest.mark.parametrize(
    ("style", "mc_gender", "profile_id", "expected_keys", "expected_gender"),
    [
        ("solo", "female", "commentary_solo", ["female"], "female"),
        ("dialogue", "female", "commentary_dialogue", ["male", "female"], None),
    ],
)
def test_legacy_commentary_selection_persists_resolved_profile_snapshot(
    client, monkeypatch, style, mc_gender, profile_id, expected_keys, expected_gender,
):
    _seed_program_profiles()
    _suppress_generation_worker(monkeypatch)
    with patch("app.api.generate._validate_url_public"):
        response = client.post(
            "/generate",
            json={
                "date": "2099-11-07",
                "url": "https://example.com/article",
                "style": style,
                "mc_gender": mc_gender,
            },
        )

    assert response.status_code == 200
    episode = EpisodeService().get_episode(response.json()["episode_id"])
    snapshot = json.loads(episode["program_snapshot"])
    assert episode["program_id"] == profile_id
    assert snapshot["id"] == profile_id
    assert [member["key"] for member in snapshot["cast"]] == expected_keys
    assert snapshot["options"]["style"] == style
    assert snapshot["options"]["mc_gender"] == expected_gender
    assert {
        key for segment in snapshot["segments"] for key in segment["speaker_keys"]
    } == set(expected_keys)


def test_program_id_database_failure_returns_503(client):
    _seed_program_profiles()
    with patch("app.api.generate.load_program_profile", side_effect=sqlite3.OperationalError("db unavailable")):
        response = client.post(
            "/generate",
            json={"date": "2099-11-04", "program_id": "radio_news_neighbor"},
        )
    assert response.status_code == 503


def test_legacy_generation_falls_back_when_program_lookup_fails(client, monkeypatch):
    _suppress_generation_worker(monkeypatch)
    with patch("app.api.generate.load_program_profile", side_effect=sqlite3.OperationalError("db unavailable")), \
         patch("app.api.generate.run_radio_pipeline", return_value=None):
        response = client.post(
            "/generate", json={"date": "2099-11-06", "news_source": "yahoo_news"}
        )

    assert response.status_code == 200
    episode = EpisodeService().get_episode(response.json()["episode_id"])
    assert json.loads(episode["program_snapshot"])["id"] == "radio_news_neighbor"


def test_legacy_generation_falls_back_when_program_table_is_empty(client, monkeypatch):
    _seed_program_profiles()
    _suppress_generation_worker(monkeypatch)
    with get_db_connection() as conn:
        conn.execute("DELETE FROM programs")

    response = client.post(
        "/generate", json={"date": "2099-11-05", "news_source": "yahoo_news"}
    )

    assert response.status_code == 200
    episode = EpisodeService().get_episode(response.json()["episode_id"])
    assert json.loads(episode["program_snapshot"])["id"] == "radio_news_neighbor"


def test_synthesize_episode_applies_per_cast_voice_overrides(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": [
            {"speaker": "male", "text": "male line"},
            {"speaker": "female", "text": "female line"},
        ]}),
        encoding="utf-8",
    )

    def synthesize_line(_text, _speaker, path, **_kwargs):
        Path(path).write_bytes(b"wav")
        return True

    with patch("app.batch.synthesize_voicevox.VoicevoxClient") as client_cls:
        client_cls.return_value.synthesize_line.side_effect = synthesize_line
        success_count = synthesize_episode(
            str(episode_dir), tts_engine="voicevox", speaker_male=1, speaker_female=2,
            speaker_overrides={"male": 901, "female": 902},
        )

    assert success_count == 2
    assert client_cls.call_args.kwargs["speaker_overrides"] == {"male": 901, "female": 902}

    from app.services.voicevox_client import VoicevoxClient
    from app.services.fishs2pro_client import FishS2ProClient

    assert VoicevoxClient("http://example", 1, 2, {"male": 901}).get_speaker_id("male") == 901
    assert FishS2ProClient("http://example", "global-male", "global-female", {"female": "db-female"})._voice_names["female"] == "db-female"
