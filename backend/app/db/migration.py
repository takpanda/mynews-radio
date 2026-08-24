import sqlite3


def migrate_llm_call_logs(conn: sqlite3.Connection) -> bool:
    """既存DBへLLM呼び出しログの保存先を追加する。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_call_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL UNIQUE, "
        "episode_id INTEGER, phase TEXT NOT NULL, provider TEXT NOT NULL, "
        "model TEXT NOT NULL DEFAULT '', base_url TEXT NOT NULL DEFAULT '', "
        "attempt INTEGER NOT NULL, "
        "status TEXT NOT NULL CHECK (status IN ('success', 'retry', 'json_parse_failed', 'error')), "
        "latency_ms INTEGER, prompt_text TEXT NOT NULL DEFAULT '', "
        "response_text TEXT NOT NULL DEFAULT '', thinking_text TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_call_logs_episode_created "
        "ON llm_call_logs(episode_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_call_logs_created_at "
        "ON llm_call_logs(created_at)"
    )
    return True


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
    old_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(audit_logs_old)").fetchall()
    }

    def column_or(name: str, fallback: str) -> str:
        return f'"{name}"' if name in old_columns else fallback

    conn.execute(
        "INSERT INTO audit_logs "
        "(id, operation, owner_user_id, actor_user_id, generation_job_id, idempotency_key_hash, "
        " input_hash, executed_at, result, accepted, rejection_reason, started_at, ended_at, episode_id) "
        "SELECT "
        f"{column_or('id', 'NULL')}, {column_or('operation', 'NULL')}, "
        f"{column_or('owner_user_id', 'NULL')}, {column_or('actor_user_id', column_or('owner_user_id', 'NULL'))}, "
        f"{column_or('generation_job_id', 'NULL')}, {column_or('idempotency_key_hash', 'NULL')}, "
        f"{column_or('input_hash', 'NULL')}, {column_or('executed_at', 'CURRENT_TIMESTAMP')}, "
        f"{column_or('result', 'NULL')}, {column_or('accepted', '1')}, "
        f"{column_or('rejection_reason', 'NULL')}, {column_or('started_at', 'NULL')}, "
        f"{column_or('ended_at', 'NULL')}, {column_or('episode_id', 'NULL')} "
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
