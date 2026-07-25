import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import settings_service


def test_validate_settings_enforces_mvp_contract():
    settings = settings_service.validate_settings(
        ["technology", "business"], ["sports"], "short"
    )
    assert settings.to_dict() == {
        "priority_themes": ["technology", "business"],
        "excluded_themes": ["sports"],
        "duration_preset": "short",
    }
    assert settings.generation_params()["max_articles"] == 6
    with pytest.raises(ValueError):
        settings_service.validate_settings(["technology"] * 4, [], "normal")
    with pytest.raises(ValueError):
        settings_service.validate_settings(["politics"], [], "normal")
    with pytest.raises(ValueError):
        settings_service.validate_settings([], [], "custom")
    with pytest.raises(ValueError):
        settings_service.validate_settings(["technology"], ["technology"], "normal")


@pytest.mark.parametrize(
    ("preset", "max_articles", "min_score"),
    [("short", 6, 4), ("normal", 10, 3), ("long", 14, 2)],
)
def test_all_duration_presets_are_generation_contracts(preset, max_articles, min_score):
    value = settings_service.validate_settings([], [], preset)
    assert value.generation_params()["max_articles"] == max_articles
    assert value.generation_params()["min_importance_score"] == min_score


def test_explicit_max_articles_wins_over_long_saved_duration():
    from app.batch.radio_pipeline import _resolve_max_articles

    profile = settings_service.validate_settings([], [], "long")
    assert _resolve_max_articles(10, profile.generation_params()) == 10


def test_get_settings_falls_back_to_default_on_database_failure(monkeypatch):
    def broken_connection():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(settings_service, "get_db_connection", broken_connection)
    assert settings_service.get_settings_or_default() == settings_service.default_settings()


def test_save_get_and_reset_settings(monkeypatch, tmp_path):
    db_path = tmp_path / "settings.db"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(settings_service, "get_settings", FakeSettings, raising=False)
    # Patch the imported connection context manager without importing the app.
    from app.db import connection
    monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
    with connection.get_db_connection() as conn:
        conn.execute(
            "CREATE TABLE user_settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
            "priority_themes TEXT NOT NULL, excluded_themes TEXT NOT NULL, "
            "duration_preset TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    value = settings_service.validate_settings(["society"], ["sports"], "long")
    settings_service.save_settings(value)
    assert settings_service.get_settings_or_default() == value
    assert settings_service.reset_settings() == settings_service.default_settings()


def test_schema_can_be_applied_again_without_losing_settings(monkeypatch, tmp_path):
    db_path = tmp_path / "schema-reapply.db"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    from app.db import connection
    monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    with connection.get_db_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    value = settings_service.validate_settings(["technology"], [], "short")
    settings_service.save_settings(value)
    with connection.get_db_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    assert settings_service.get_settings_or_default() == value


def test_settings_api_crud_validation_and_failures(client, monkeypatch):
    assert client.get("/settings").status_code == 200
    assert client.get("/settings").json()["duration_preset"] == "normal"

    saved = client.put(
        "/settings",
        json={"priority_themes": ["technology"], "excluded_themes": ["sports"], "duration_preset": "short"},
    )
    assert saved.status_code == 200
    assert client.get("/settings").json()["duration_preset"] == "short"
    assert client.put(
        "/settings",
        json={"priority_themes": ["technology"], "excluded_themes": ["technology"], "duration_preset": "normal"},
    ).status_code == 422
    assert client.put("/settings", json={"unknown": True}).status_code == 422
    assert client.put("/settings", json={"duration_preset": "invalid"}).status_code == 422

    from app.api import settings as settings_api
    monkeypatch.setattr(settings_api, "save_settings", lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert client.put("/settings", json={"duration_preset": "normal"}).status_code == 503
    monkeypatch.setattr(settings_api, "reset_settings", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert client.delete("/settings").status_code == 503


def test_settings_requires_authentication():
    from app.main import app
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/settings")
    assert response.status_code in (401, 403)


def test_generate_uses_saved_settings_and_falls_back_on_read_error(monkeypatch):
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    settings_service.save_settings(
        settings_service.validate_settings(["business"], ["sports"], "long")
    )
    episode_id = EpisodeService().create_episode("2099-12-01", status="generating")
    captured = []
    monkeypatch.setattr(generate_api, "run_radio_pipeline", lambda *args, **kwargs: captured.append(kwargs))
    generate_api._run_generation(episode_id, generate_api.GenerateRequest(date="2099-12-01"))
    assert captured[0]["program_settings"].priority_themes == ("business",)
    assert captured[0]["program_settings"].duration_preset == "long"

    def broken_connection():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(settings_service, "get_db_connection", broken_connection)
    captured.clear()
    generate_api._run_generation(episode_id, generate_api.GenerateRequest(date="2099-12-01"))
    assert captured[0]["program_settings"] == settings_service.default_settings()
