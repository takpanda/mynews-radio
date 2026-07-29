import sqlite3


def migrate_audit_logs(conn: sqlite3.Connection) -> bool:
    """旧監査ログ（rejected 非対応）を拡張スキーマへ移行する。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audit_logs'"
    ).fetchone()
    if not row or "rejected" in (row["sql"] or ""):
        return False

    conn.execute("ALTER TABLE audit_logs RENAME TO audit_logs_old")
    conn.execute(
        "CREATE TABLE audit_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL, owner_user_id INTEGER, "
        "actor_user_id INTEGER, generation_job_id INTEGER, idempotency_key_hash TEXT, input_hash TEXT, "
        "executed_at TEXT NOT NULL, "
        "result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure', 'rejected')), "
        "accepted INTEGER NOT NULL DEFAULT 1, rejection_reason TEXT, started_at TEXT, ended_at TEXT, "
        "episode_id INTEGER, "
        "FOREIGN KEY (owner_user_id) REFERENCES admin_users(id) ON DELETE SET NULL)"
    )
    conn.execute(
        "INSERT INTO audit_logs "
        "(id, operation, owner_user_id, actor_user_id, executed_at, result, accepted, episode_id) "
        "SELECT id, operation, owner_user_id, owner_user_id, executed_at, result, 1, episode_id "
        "FROM audit_logs_old"
    )
    conn.execute("DROP TABLE audit_logs_old")
    return True


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
        "is_active INTEGER NOT NULL DEFAULT 1, "
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


def migrate_enabled_to_is_active(conn: sqlite3.Connection) -> bool:
    """dictionary_entries.enabled → is_active にリネームする。

    PRAGMA table_info で enabled カラムの存在を確認し、
    存在する場合のみ ALTER TABLE RENAME COLUMN を実行する。

    Returns:
        True if migration was performed, False otherwise.
    """
    columns = conn.execute(
        "PRAGMA table_info(dictionary_entries)"
    ).fetchall()
    has_enabled = any(c["name"] == "enabled" for c in columns)
    if not has_enabled:
        return False

    conn.execute("ALTER TABLE dictionary_entries RENAME COLUMN enabled TO is_active")
    return True
