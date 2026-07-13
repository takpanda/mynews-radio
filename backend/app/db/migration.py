import sqlite3


def migrate_dictionary_constraint(conn: sqlite3.Connection) -> bool:
    """UNIQUE(surface) → UNIQUE(surface, reading) に移行する。

    PRAGMA index_info で自動インデックスの列構成を確認し、
    surface 単独のUNIQUE制約の場合のみテーブル再構築を実行する。

    Returns:
        True if migration was performed, False otherwise.
    """
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dictionary_entries' AND name LIKE 'sqlite_autoindex_dictionary_entries%'"
    ).fetchone()
    if not idx:
        return False

    cols = conn.execute(
        f"PRAGMA index_info('{idx['name']}')"
    ).fetchall()
    # UNIQUE(surface) 単独なら1カラム、UNIQUE(surface, reading) なら2カラム
    if not (len(cols) == 1 and cols[0]['name'] == 'surface'):
        return False

    conn.execute("ALTER TABLE dictionary_entries RENAME TO dictionary_entries_old")
    conn.execute(
        "CREATE TABLE dictionary_entries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "surface TEXT NOT NULL, "
        "reading TEXT NOT NULL, "
        "category TEXT DEFAULT '', "
        "enabled INTEGER NOT NULL DEFAULT 1, "
        "notes TEXT DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(surface, reading))"
    )
    conn.execute(
        "INSERT INTO dictionary_entries "
        "SELECT id, surface, reading, category, enabled, COALESCE(notes, ''), created_at, updated_at "
        "FROM dictionary_entries_old"
    )
    conn.execute("DROP TABLE dictionary_entries_old")
    return True
