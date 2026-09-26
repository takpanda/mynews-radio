import json
import re
import sqlite3
from pathlib import Path

import pytest

from app.db.migration import migrate_llm_call_logs, migrate_prompt_templates
from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS


PROMPTS_DIR = Path(__file__).parents[1] / "app" / "prompts"


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE programs (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE llm_call_logs (id INTEGER PRIMARY KEY, call_id TEXT NOT NULL UNIQUE, episode_id INTEGER)"
    )
    return conn


def test_prompt_template_migration_seeds_initial_versions_idempotently():
    conn = _conn()
    migrate_prompt_templates(conn)

    templates = conn.execute(
        "SELECT id, template_key, program_id, required_variables, allowed_variables "
        "FROM prompt_templates ORDER BY template_key"
    ).fetchall()
    assert {row["template_key"] for row in templates} == set(PROMPT_TEMPLATE_DEFINITIONS)
    assert all(row["program_id"] is None for row in templates)

    versions_before = conn.execute(
        "SELECT template_id, version, content, status FROM prompt_versions ORDER BY template_id"
    ).fetchall()
    assert len(versions_before) == len(PROMPT_TEMPLATE_DEFINITIONS)
    assert all(row["version"] == 1 and row["status"] == "active" for row in versions_before)
    for row in templates:
        definition = PROMPT_TEMPLATE_DEFINITIONS[row["template_key"]]
        assert json.loads(row["required_variables"]) == definition["required_variables"]
        assert json.loads(row["allowed_variables"]) == definition["allowed_variables"]

    # 既存編集を含む版に触れず、行数も増やさない。
    edited_template_id = templates[0]["id"]
    conn.execute(
        "UPDATE prompt_versions SET content = 'edited' WHERE template_id = ?",
        (edited_template_id,),
    )
    migrate_prompt_templates(conn)
    versions_after = conn.execute(
        "SELECT template_id, version, content, status FROM prompt_versions ORDER BY template_id"
    ).fetchall()
    assert [tuple(row) for row in versions_after] == [
        (
            row["template_id"], row["version"],
            "edited" if row["template_id"] == edited_template_id else row["content"], row["status"],
        )
        for row in versions_before
    ]
    assert conn.execute("SELECT COUNT(*) FROM prompt_templates").fetchone()[0] == len(PROMPT_TEMPLATE_DEFINITIONS)


def test_fresh_schema_can_be_migrated_repeatedly():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))

    migrate_llm_call_logs(conn)
    migrate_prompt_templates(conn)
    migrate_llm_call_logs(conn)
    migrate_prompt_templates(conn)

    assert conn.execute("SELECT COUNT(*) FROM prompt_templates").fetchone()[0] == len(
        PROMPT_TEMPLATE_DEFINITIONS
    )
    for row in conn.execute(
        "SELECT template_key, content FROM prompt_templates "
        "JOIN prompt_versions ON prompt_versions.template_id = prompt_templates.id"
    ):
        definition = PROMPT_TEMPLATE_DEFINITIONS[row["template_key"]]
        assert row["content"] == (PROMPTS_DIR / definition["file"]).read_text(encoding="utf-8")


def test_prompt_template_migration_preserves_legacy_logs_and_allows_null_version():
    conn = _conn()
    conn.execute("INSERT INTO llm_call_logs (id, call_id, episode_id) VALUES (1, 'legacy', NULL)")
    migrate_prompt_templates(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(llm_call_logs)")}
    assert "prompt_version_id" in columns
    assert tuple(conn.execute("SELECT id, call_id, prompt_version_id FROM llm_call_logs").fetchone()) == (
        1, "legacy", None
    )
    version_id = conn.execute("SELECT id FROM prompt_versions LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO llm_call_logs (id, call_id, episode_id, prompt_version_id) "
        "VALUES (2, 'linked', NULL, ?)",
        (version_id,),
    )
    conn.execute("DELETE FROM prompt_versions WHERE id = ?", (version_id,))
    assert conn.execute(
        "SELECT prompt_version_id FROM llm_call_logs WHERE id = 2"
    ).fetchone()[0] is None
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO llm_call_logs (id, call_id, prompt_version_id) VALUES (3, 'invalid-ref', 9999)"
        )


def test_prompt_template_and_version_constraints():
    conn = _conn()
    migrate_prompt_templates(conn)
    template_id = conn.execute(
        "SELECT id FROM prompt_templates WHERE template_key = 'category'"
    ).fetchone()["id"]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO prompt_templates (template_key) VALUES ('category')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, 'dup', 'draft')",
            (template_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 0, 'bad', 'draft')",
            (template_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 2, 'second active', 'active')",
            (template_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 2, 'bad state', 'unknown')",
            (template_id,),
        )


def test_prompt_variable_contract_matches_prompt_placeholders():
    for definition in PROMPT_TEMPLATE_DEFINITIONS.values():
        content = (PROMPTS_DIR / definition["file"]).read_text(encoding="utf-8")
        variables = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", content))
        assert variables == set(definition["required_variables"])
        assert variables <= set(definition["allowed_variables"])
