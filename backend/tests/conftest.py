import os
from pathlib import Path

import pytest
import sqlite3 as _sqlite3


@pytest.fixture(scope="session")
def app_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("data")
    db_file = str(tmp / "test.db")
    ep_dir = str(tmp / "episodes")
    os.makedirs(ep_dir, exist_ok=True)

    try:
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()
    except ImportError:
        pass

    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["EPISODES_DIR"] = ep_dir


@pytest.fixture(scope="session")
def app(app_env):
    schema_path = str(Path(__file__).parent.parent / "app" / "db" / "schema.sql")

    from urllib.parse import urlparse
    parsed = urlparse(os.environ["DATABASE_URL"])
    db_path = parsed.path

    conn = _sqlite3.connect(db_path)
    conn.row_factory = _sqlite3.Row
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN phase TEXT DEFAULT ''")
    except Exception:
        pass
    conn.commit()
    conn.close()

    from app import main as _main_mod
    yield _main_mod.app


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)
