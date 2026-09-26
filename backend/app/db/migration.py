import sqlite3
import json
from dataclasses import replace
from pathlib import Path


SYSTEM_OWNER_USERNAME = "__generation_queue_system__"


def migrate_program_profiles(conn: sqlite3.Connection) -> bool:
    """番組・MC定義を追加し、現行の4番組を未登録時のみ初期投入する。"""
    from app.programs.profiles import get_default_profile
    from app.programs.serialization import program_profile_to_definition

    conn.execute(
        "CREATE TABLE IF NOT EXISTS mc_profiles ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', "
        "voice_fishs2pro TEXT, voice_aivispeech INTEGER, voice_voicevox INTEGER, "
        "is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)), "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS programs ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "kind TEXT NOT NULL CHECK (kind IN ('radio', 'commentary')), "
        "definition TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)), "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()}
    if "program_id" not in columns:
        conn.execute(
            "ALTER TABLE episodes ADD COLUMN program_id TEXT "
            "REFERENCES programs(id) ON DELETE SET NULL"
        )
    if "program_snapshot" not in columns:
        conn.execute("ALTER TABLE episodes ADD COLUMN program_snapshot TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_program_id ON episodes(program_id)")

    mc_profiles = (
        ("radio_male", "田村", "メインMC"),
        ("radio_female", "山口", "パートナーMC"),
        ("commentary_male", "", "解説者"),
        ("commentary_female", "", "聞き手"),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO mc_profiles (id, name, role) VALUES (?, ?, ?)",
        mc_profiles,
    )
    profiles = (
        get_default_profile(kind="radio"),
        get_default_profile(kind="radio", news_source="hatena_bookmark"),
        get_default_profile(kind="commentary", style="solo"),
        get_default_profile(kind="commentary", style="dialogue"),
    )
    for profile in profiles:
        if profile.id in {"commentary_solo", "commentary_dialogue"}:
            profile = replace(
                profile,
                name="解説 solo" if profile.id == "commentary_solo" else "解説 dialogue",
            )
        conn.execute(
            "INSERT OR IGNORE INTO programs (id, name, kind, definition) VALUES (?, ?, ?, ?)",
            (
                profile.id,
                profile.name,
                profile.kind,
                json.dumps(program_profile_to_definition(profile), ensure_ascii=False),
            ),
        )
    return True


def migrate_generation_jobs(conn: sqlite3.Connection) -> bool:
    """既存の生成ジョブを待機キュー対応スキーマへ再構築する。

    SQLiteでは既存CHECK制約へ ``waiting`` を追加できないため、行を保持した
    まま一時テーブルへコピーして再構築する。payloadが無い旧行は空JSONで
    復元し、冪等性・監査ログから参照されるidも維持する。
    """
    def table_exists(name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone() is not None

    # テーブル再構築の途中（DROP後のプロセス終了など）で残った一時テーブルを
    # 起動時に復旧する。両方残っている場合は、旧本体を正として stale な一時表を
    # 破棄し、通常の移行を続行する。
    if table_exists("generation_jobs_new"):
        foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        if foreign_keys_enabled:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            if table_exists("generation_jobs"):
                conn.execute("DROP TABLE generation_jobs_new")
            else:
                conn.execute("ALTER TABLE generation_jobs_new RENAME TO generation_jobs")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_owner_status ON generation_jobs(owner_user_id, status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_claimed_at ON generation_jobs(claimed_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_ip_status ON generation_jobs(client_ip_hash, status)")
        finally:
            if foreign_keys_enabled:
                conn.execute("PRAGMA foreign_keys = ON")

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'generation_jobs'"
    ).fetchone()
    if not row:
        return False
    sql = row[0] or ""
    columns = {item[1] for item in conn.execute("PRAGMA table_info(generation_jobs)").fetchall()}
    if "waiting" in sql and "payload" in columns:
        return False

    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_enabled:
        # generation_jobsを参照する詳細ログのFKを壊さずに親テーブルを再構築する。
        # この関数は呼び出し元のトランザクション開始前に実行される。
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
        "CREATE TABLE generation_jobs_new ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "owner_user_id INTEGER NOT NULL, operation TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL, input_hash TEXT NOT NULL, "
        "client_ip_hash TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}', "
        "episode_id INTEGER, status TEXT NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('waiting', 'active', 'completed', 'failed')), "
        "claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT, "
        "FOREIGN KEY (owner_user_id) REFERENCES admin_users(id) ON DELETE CASCADE, "
        "FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL, "
        "UNIQUE(owner_user_id, operation, idempotency_key))"
        )
        old_columns = {item[1] for item in conn.execute("PRAGMA table_info(generation_jobs)").fetchall()}

        def old_column(name: str, fallback: str) -> str:
            return f'"{name}"' if name in old_columns else fallback

        empty_text = "''"
        failed_status = "'failed'"

        conn.execute(
        "INSERT INTO generation_jobs_new "
        "(id, owner_user_id, operation, idempotency_key, input_hash, client_ip_hash, payload, "
        " episode_id, status, claimed_at, finished_at) SELECT "
        f"{old_column('id', 'NULL')}, {old_column('owner_user_id', 'NULL')}, "
        f"{old_column('operation', 'NULL')}, {old_column('idempotency_key', empty_text)}, "
        f"{old_column('input_hash', empty_text)}, {old_column('client_ip_hash', empty_text)}, '{{}}', "
        f"{old_column('episode_id', 'NULL')}, {old_column('status', failed_status)}, "
        f"{old_column('claimed_at', 'CURRENT_TIMESTAMP')}, {old_column('finished_at', 'NULL')} "
        "FROM generation_jobs"
        )
        conn.execute("DROP TABLE generation_jobs")
        conn.execute("ALTER TABLE generation_jobs_new RENAME TO generation_jobs")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_owner_status ON generation_jobs(owner_user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_claimed_at ON generation_jobs(claimed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_jobs_ip_status ON generation_jobs(client_ip_hash, status)")
    finally:
        if foreign_keys_enabled:
            conn.execute("PRAGMA foreign_keys = ON")
    return True


def ensure_generation_system_owner(conn: sqlite3.Connection) -> int:
    """cronジョブ用のログイン不能な所有者を冪等に作成し、そのidを返す。"""
    conn.execute(
        "INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES (?, ?)",
        (SYSTEM_OWNER_USERNAME, "disabled$generation_queue"),
    )
    row = conn.execute(
        "SELECT id FROM admin_users WHERE username = ?", (SYSTEM_OWNER_USERNAME,)
    ).fetchone()
    return int(row[0])


FEMALE_MC_SAMPLE_TEXT = "こんにちは、ニュースの時間です。今日の主な話題をお伝えします。"


def migrate_female_mc_candidates(conn: sqlite3.Connection) -> bool:
    """女性MC候補マスタを追加し、既存の固定候補を初期投入する。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS female_mc_candidates ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "voice_name TEXT NOT NULL UNIQUE, "
        "display_name TEXT NOT NULL, "
        "sample_text TEXT NOT NULL, "
        "is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)), "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_female_mc_candidates_active "
        "ON female_mc_candidates(is_active, voice_name)"
    )
    conn.executemany(
        "INSERT OR IGNORE INTO female_mc_candidates "
        "(voice_name, display_name, sample_text) VALUES (?, ?, ?)",
        (
            ("female", "female", FEMALE_MC_SAMPLE_TEXT),
            ("morigawa", "morigawa", FEMALE_MC_SAMPLE_TEXT),
        ),
    )
    return True


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


def migrate_prompt_templates(conn: sqlite3.Connection) -> bool:
    """プロンプト版管理テーブルとファイル由来の共通active版を冪等に追加する。"""
    from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS

    conn.execute(
        "CREATE TABLE IF NOT EXISTS prompt_templates ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, template_key TEXT NOT NULL, program_id TEXT, "
        "required_variables TEXT NOT NULL DEFAULT '[]', allowed_variables TEXT NOT NULL DEFAULT '[]', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE CASCADE)"
    )
    # NULL を含む UNIQUE(template_key, program_id) は SQLite では重複を許すため、
    # 共通スコープを空文字へ正規化した式インデックスで一意性を保証する。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_templates_key_program "
        "ON prompt_templates(template_key, COALESCE(program_id, ''))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prompt_versions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, template_id INTEGER NOT NULL, version INTEGER NOT NULL CHECK (version > 0), "
        "content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft' "
        "CHECK (status IN ('draft', 'active', 'archived')), "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(template_id, version), FOREIGN KEY (template_id) REFERENCES prompt_templates(id) ON DELETE CASCADE)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_versions_one_active "
        "ON prompt_versions(template_id) WHERE status = 'active'"
    )
    log_columns = {row["name"] for row in conn.execute("PRAGMA table_info(llm_call_logs)").fetchall()}
    if "prompt_version_id" not in log_columns:
        conn.execute(
            "ALTER TABLE llm_call_logs ADD COLUMN prompt_version_id INTEGER "
            "REFERENCES prompt_versions(id) ON DELETE SET NULL"
        )

    prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
    for template_key, definition in PROMPT_TEMPLATE_DEFINITIONS.items():
        conn.execute(
            "INSERT OR IGNORE INTO prompt_templates "
            "(template_key, program_id, required_variables, allowed_variables) VALUES (?, NULL, ?, ?)",
            (
                template_key,
                json.dumps(definition["required_variables"], ensure_ascii=False),
                json.dumps(definition["allowed_variables"], ensure_ascii=False),
            ),
        )
        template = conn.execute(
            "SELECT id FROM prompt_templates WHERE template_key = ? AND program_id IS NULL",
            (template_key,),
        ).fetchone()
        has_versions = conn.execute(
            "SELECT 1 FROM prompt_versions WHERE template_id = ? LIMIT 1", (template["id"],)
        ).fetchone()
        if not has_versions:
            content = (prompt_dir / definition["file"]).read_text(encoding="utf-8")
            conn.execute(
                "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, ?, 'active')",
                (template["id"], content),
            )
    return True


def migrate_prompt_version_audit_events(conn: sqlite3.Connection) -> bool:
    """プロンプト版切替・ロールバックの追跡可能な監査関係を追加する。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prompt_version_audit_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, audit_log_id INTEGER NOT NULL UNIQUE, "
        "template_id INTEGER NOT NULL, action TEXT NOT NULL CHECK (action IN ('activate', 'rollback')), "
        "source_version_id INTEGER, previous_active_version_id INTEGER, new_version_id INTEGER NOT NULL, "
        "change_note TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (audit_log_id) REFERENCES audit_logs(id) ON DELETE CASCADE, "
        "FOREIGN KEY (template_id) REFERENCES prompt_templates(id) ON DELETE CASCADE, "
        "FOREIGN KEY (source_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL, "
        "FOREIGN KEY (previous_active_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL, "
        "FOREIGN KEY (new_version_id) REFERENCES prompt_versions(id) ON DELETE CASCADE)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_version_audit_template_created "
        "ON prompt_version_audit_events(template_id, created_at DESC)"
    )
    return True


def migrate_script_revisions(conn: sqlite3.Connection) -> bool:
    """台本レビュー用の状態列と改訂履歴を追加する。既存episode状態は変更しない。"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()}
    if "review_mode" not in columns:
        conn.execute("ALTER TABLE episodes ADD COLUMN review_mode TEXT NOT NULL DEFAULT 'on_failure'")
    if "review_cycle" not in columns:
        conn.execute("ALTER TABLE episodes ADD COLUMN review_cycle INTEGER NOT NULL DEFAULT 0")
    has_push_subscriptions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='push_subscriptions'"
    ).fetchone()
    subscription_columns = {row["name"] for row in conn.execute("PRAGMA table_info(push_subscriptions)").fetchall()}
    if has_push_subscriptions and "admin_user_id" not in subscription_columns:
        conn.execute("ALTER TABLE push_subscriptions ADD COLUMN admin_user_id INTEGER REFERENCES admin_users(id) ON DELETE SET NULL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS script_revisions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id INTEGER NOT NULL, "
        "revision INTEGER NOT NULL, script_json TEXT NOT NULL, "
        "source TEXT NOT NULL CHECK (source IN ('generated', 'reviewed', 'human')), "
        "actor_user_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(episode_id, revision), "
        "FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE, "
        "FOREIGN KEY (actor_user_id) REFERENCES admin_users(id) ON DELETE SET NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_script_revisions_episode_revision "
        "ON script_revisions(episode_id, revision DESC)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS script_preview_rate_limits ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, admin_user_id INTEGER NOT NULL, episode_id INTEGER NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE, "
        "FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_script_preview_admin_created ON script_preview_rate_limits(admin_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_script_preview_episode_created ON script_preview_rate_limits(episode_id, created_at)")
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
