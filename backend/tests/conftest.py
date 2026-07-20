import os
import threading
import time
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
        conn.execute("DROP INDEX IF EXISTS idx_episodes_generating_date")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN seq INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_date_type ON episodes(episode_date, type)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE dictionary_entries ADD COLUMN notes TEXT DEFAULT ''")
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
    monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")

    # Clear lru_cache on get_settings so lazy access picks up the new env vars
    from app import config as cfg_mod
    if hasattr(cfg_mod.get_settings, "cache_clear"):
        cfg_mod.get_settings.cache_clear()

    yield


@pytest.fixture(autouse=True)
def no_daemon_thread_leaks():
    """Make all threads non-daemon so background threads from API tests
    can be tracked and joined before fixture cleanup, preventing orphaned
    threads from writing to cleaned-up temp dirs (//app errors)."""
    original_start = threading.Thread.start
    threads = []

    def _tracked_start(self):
        self.daemon = False
        threads.append(self)
        return original_start(self)

    threading.Thread.start = _tracked_start
    yield
    threading.Thread.start = original_start

    deadline = time.monotonic() + 5.0
    for t in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if t.is_alive():
            t.join(timeout=max(0.01, remaining))


@pytest.fixture
def client():
    from app.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    with patch("app.api.generate.run_radio_pipeline", return_value=None):
        yield TestClient(app)
