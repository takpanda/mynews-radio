import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.db.migration import migrate_prompt_templates
from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS
from app.prompts import service


PROMPTS_DIR = Path(__file__).parents[1] / "app" / "prompts"


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        "CREATE TABLE programs (id TEXT PRIMARY KEY);"
        "CREATE TABLE llm_call_logs (id INTEGER PRIMARY KEY, call_id TEXT UNIQUE, episode_id INTEGER);"
    )
    migrate_prompt_templates(conn)
    return conn


def _install_connection(monkeypatch, conn):
    @contextmanager
    def connection_context():
        yield conn

    monkeypatch.setattr(service, "get_db_connection", connection_context)


def _values(definition):
    result = {}
    for variable in definition["allowed_variables"]:
        result[variable] = 42 if variable.endswith("id") or variable == "article_id" else f"value:{variable}"
    return result


def _legacy_format(content, values):
    """従来ファイルを str.format した完成出力。"""
    return content.format(**values)


def test_file_prompts_match_legacy_format_golden_output():
    for template_key, definition in PROMPT_TEMPLATE_DEFINITIONS.items():
        content = (PROMPTS_DIR / definition["file"]).read_text(encoding="utf-8")
        values = _values(definition)
        actual = service.render_prompt_template(
            content,
            values,
            required_variables=definition["required_variables"],
            allowed_variables=definition["allowed_variables"],
        )
        assert actual == _legacy_format(content, values), template_key


def test_seeded_common_active_prompts_match_file_golden_output(monkeypatch):
    conn = _connection()
    _install_connection(monkeypatch, conn)

    for template_key, definition in PROMPT_TEMPLATE_DEFINITIONS.items():
        result = service.render_prompt(template_key, _values(definition))
        file_content = (PROMPTS_DIR / definition["file"]).read_text(encoding="utf-8")
        assert result.source == "common"
        assert result.version_id is not None
        assert result.text == _legacy_format(file_content, _values(definition)), template_key


def test_program_active_is_preferred_then_common_and_file(monkeypatch):
    conn = _connection()
    conn.execute("INSERT INTO programs (id) VALUES ('program-1')")
    template_id = conn.execute(
        "INSERT INTO prompt_templates (template_key, program_id, required_variables, allowed_variables) "
        "SELECT template_key, 'program-1', required_variables, allowed_variables "
        "FROM prompt_templates WHERE template_key = 'category'"
    ).lastrowid
    conn.execute(
        "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, ?, 'active')",
        (template_id, "program {source} {categories}"),
    )
    _install_connection(monkeypatch, conn)
    values = {"source": "program-source", "categories": "program-categories"}

    assert service.render_prompt("category", values, program_id="program-1").text == (
        "program program-source program-categories"
    )
    assert service.render_prompt("category", values, program_id="missing").source == "common"

    conn.execute("DELETE FROM prompt_versions")
    assert service.render_prompt("category", values, program_id="program-1").source == "file"


def test_invalid_program_active_version_falls_back_to_common(monkeypatch):
    conn = _connection()
    conn.execute("INSERT INTO programs (id) VALUES ('program-1')")
    common = conn.execute(
        "SELECT id, required_variables, allowed_variables FROM prompt_templates "
        "WHERE template_key = 'category' AND program_id IS NULL"
    ).fetchone()
    program_id = conn.execute(
        "INSERT INTO prompt_templates (template_key, program_id, required_variables, allowed_variables) "
        "VALUES ('category', 'program-1', ?, ?)",
        (common["required_variables"], common["allowed_variables"]),
    ).lastrowid
    conn.execute(
        "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, ?, 'active')",
        (program_id, "unknown {not_allowed}"),
    )
    _install_connection(monkeypatch, conn)

    result = service.render_prompt(
        "category", {"source": "body", "categories": "list"}, program_id="program-1"
    )
    assert result.source == "common"
    assert result.version_id is not None


def test_invalid_common_active_version_falls_back_to_file(monkeypatch):
    conn = _connection()
    conn.execute(
        "UPDATE prompt_versions SET content = 'invalid {unknown}' "
        "WHERE template_id = (SELECT id FROM prompt_templates WHERE template_key = 'category')"
    )
    _install_connection(monkeypatch, conn)

    result = service.render_prompt("category", {"source": "body", "categories": "list"})
    assert result.source == "file"
    assert result.version_id is None


def test_database_failure_uses_file_and_keeps_json_braces(monkeypatch):
    @contextmanager
    def failing_connection():
        raise sqlite3.OperationalError("database unavailable")
        yield

    monkeypatch.setattr(service, "get_db_connection", failing_connection)
    result = service.render_prompt("category", {"categories": "A", "source": "B"})

    assert result.source == "file"
    assert '{"categories": ["カテゴリ"]}' in result.text


def test_validation_rejects_missing_required_and_unknown_variables():
    with pytest.raises(service.PromptTemplateError, match="missing required"):
        service.validate_prompt_template(
            "{categories}", required_variables=("categories", "source"), allowed_variables=("categories", "source")
        )
    with pytest.raises(service.PromptTemplateError, match="unknown variables"):
        service.validate_prompt_template(
            "{categories} {source} {surprise}",
            required_variables=("categories", "source"),
            allowed_variables=("categories", "source"),
        )


def test_json_braces_are_not_variables_and_missing_render_values_are_rejected():
    content = '{"example": {"items": []}, "source": "{source}"}'
    assert service.extract_prompt_variables(content) == {"source"}
    rendered = service.render_prompt_template(
        content,
        {"source": "news"},
        required_variables=("source",),
        allowed_variables=("source",),
    )
    assert rendered == '{"example": {"items": []}, "source": "news"}'
    with pytest.raises(service.PromptTemplateError, match="missing render values"):
        service.render_prompt_template(
            "{source}",
            {},
            required_variables=("source",),
            allowed_variables=("source",),
        )


def test_escaped_known_and_unknown_variable_names_remain_literal():
    content = "{{source}} {{unknown}} {source}"
    variables = {"source": "replacement"}

    rendered = service.render_prompt_template(
        content,
        variables,
        required_variables=("source",),
        allowed_variables=("source",),
    )

    assert rendered == "{source} {unknown} replacement"
    assert rendered == _legacy_format(content, variables)
