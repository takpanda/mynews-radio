import sqlite3

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
