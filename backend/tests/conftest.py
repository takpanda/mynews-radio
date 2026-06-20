import os
from pathlib import Path
import sqlite3

import pytest


def _fresh_db(tmp_path):
    """Create a fresh DB file with schema + phase column migration."""
    db_file = tmp_path / "test.db"
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    schema_path = str(Path(__file__).parent.parent / "app" / "db" / "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN phase TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN generation_message TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_generating_date ON episodes(episode_date) WHERE status = 'generating'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

    return db_file, ep_dir


@pytest.fixture(autouse=True)
def test_env(tmp_path, monkeypatch):
    """Set up fresh DB + env vars for each test function."""
    db_file, ep_dir = _fresh_db(tmp_path)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("EPISODES_DIR", str(ep_dir))

    # Clear lru_cache on get_settings so lazy access picks up the new env vars
    from app import config as cfg_mod
    if hasattr(cfg_mod.get_settings, "cache_clear"):
        cfg_mod.get_settings.cache_clear()

    yield


@pytest.fixture
def client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
