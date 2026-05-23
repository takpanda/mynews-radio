import sqlite3
import os
from contextlib import contextmanager
from urllib.parse import urlparse

from app.config import get_settings


def _resolve_sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"Only sqlite URLs are supported. got={database_url}")

    parsed = urlparse(database_url)
    path = parsed.path
    if not path:
        raise ValueError(f"Invalid sqlite database url: {database_url}")

    return path


@contextmanager
def get_db_connection() -> sqlite3.Connection:
    settings = get_settings()
    db_path = _resolve_sqlite_path(settings.database_url)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
