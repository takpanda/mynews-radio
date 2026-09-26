"""管理者向けプロンプトテンプレート・版管理API。"""

import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_admin_with_token
from app.audit import hash_input, insert_audit_log
from app.db.connection import get_db_connection
from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS
from app.prompts.service import (
    PromptTemplateError,
    render_prompt_template,
    validate_prompt_template,
)

router = APIRouter(prefix="/admin", tags=["admin-prompts"])
AdminContext = Annotated[tuple[int, str], Depends(require_admin_with_token)]
EPISODES_DIR = Path(os.getenv("EPISODES_DIR", "data/episodes"))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptInput(StrictModel):
    template_key: str = Field(min_length=1, max_length=100)
    program_id: str | None = Field(default=None, min_length=1, max_length=100)


class VersionInput(StrictModel):
    content: str = Field(min_length=1, max_length=200_000)


class ActivationInput(StrictModel):
    change_note: str = Field(min_length=1, max_length=1000)
    expected_active_version_id: int | None = Field(..., ge=1)


class RollbackInput(ActivationInput):
    pass


class RenderInput(StrictModel):
    episode_id: int = Field(ge=1)


class PreviewInput(RenderInput):
    template_key: str = Field(min_length=1, max_length=100)


def _admin_audit(conn, operation: str, actor: int, payload: dict) -> int:
    return insert_audit_log(
        conn,
        operation=operation,
        actor_user_id=actor if actor > 0 else None,
        result="success",
        input_hash=hash_input(payload),
    )


def _get_definition(template_key: str) -> dict:
    definition = PROMPT_TEMPLATE_DEFINITIONS.get(template_key)
    if definition is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return definition


def _validate_content(template_key: str, content: str) -> None:
    definition = _get_definition(template_key)
    try:
        validate_prompt_template(
            content,
            required_variables=definition["required_variables"],
            allowed_variables=definition["allowed_variables"],
        )
    except PromptTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _episode_summaries(episode_id: int):
    with get_db_connection() as conn:
        episode = conn.execute("SELECT id FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    path = EPISODES_DIR / str(episode_id) / "summaries.json"
    try:
        summaries = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Episode summaries not found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Episode summaries are invalid") from exc
    if not isinstance(summaries, (list, dict)):
        raise HTTPException(status_code=422, detail="Episode summaries are invalid")
    return summaries


def _render(version, definition: dict, summaries) -> str:
    variables = {
        name: json.dumps(summaries, ensure_ascii=False, indent=2) if name == "summaries_json" else ""
        for name in definition["allowed_variables"]
    }
    try:
        return render_prompt_template(
            version["content"], variables,
            required_variables=definition["required_variables"],
            allowed_variables=definition["allowed_variables"],
        )
    except PromptTemplateError as exc:
        raise HTTPException(status_code=422, detail=f"Prompt version cannot be rendered: {exc}") from exc


@router.get("/prompts")
def list_prompts(_: AdminContext, program_id: str | None = None) -> list[dict]:
    with get_db_connection() as conn:
        if program_id is not None and conn.execute(
            "SELECT 1 FROM programs WHERE id = ?", (program_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Program not found")
        query = (
            "SELECT pt.*, (SELECT json_group_array(json_object('id', pv.id, 'version', pv.version, "
            "'status', pv.status, 'created_at', pv.created_at, 'updated_at', pv.updated_at)) "
            "FROM prompt_versions pv WHERE pv.template_id = pt.id ORDER BY pv.version DESC) AS versions "
            "FROM prompt_templates pt"
        )
        params: tuple = ()
        if program_id is not None:
            query += " WHERE pt.program_id = ?"
            params = (program_id,)
        query += " ORDER BY pt.template_key, pt.program_id"
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["required_variables"] = json.loads(item["required_variables"])
        item["allowed_variables"] = json.loads(item["allowed_variables"])
        item["versions"] = json.loads(item["versions"] or "[]")
        result.append(item)
    return result


@router.post("/prompts", status_code=201)
def create_prompt(body: PromptInput, admin: AdminContext) -> dict:
    definition = _get_definition(body.template_key)
    with get_db_connection() as conn:
        if body.program_id is not None and conn.execute(
            "SELECT 1 FROM programs WHERE id = ?", (body.program_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Program not found")
        if conn.execute(
            "SELECT 1 FROM prompt_templates WHERE template_key = ? AND program_id IS ?",
            (body.template_key, body.program_id),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Prompt template already exists")
        cursor = conn.execute(
            "INSERT INTO prompt_templates(template_key, program_id, required_variables, allowed_variables) "
            "VALUES (?, ?, ?, ?)",
            (body.template_key, body.program_id,
             json.dumps(definition["required_variables"]), json.dumps(definition["allowed_variables"])),
        )
        _admin_audit(conn, "admin_prompt_create", admin[0], body.model_dump())
        return {"id": cursor.lastrowid, "template_key": body.template_key, "program_id": body.program_id,
                "required_variables": definition["required_variables"],
                "allowed_variables": definition["allowed_variables"], "versions": []}


@router.get("/prompts/{prompt_id}/versions")
def list_prompt_versions(prompt_id: int, _: AdminContext) -> dict:
    with get_db_connection() as conn:
        template = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
        if template is None:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        versions = conn.execute(
            "SELECT id, version, content, status, created_at, updated_at FROM prompt_versions "
            "WHERE template_id = ? ORDER BY version DESC", (prompt_id,),
        ).fetchall()
    return {"prompt_id": prompt_id, "template_key": template["template_key"],
            "program_id": template["program_id"], "versions": [dict(row) for row in versions]}


@router.post("/prompts/{prompt_id}/versions", status_code=201)
def create_prompt_version(prompt_id: int, body: VersionInput, admin: AdminContext) -> dict:
    with get_db_connection() as conn:
        template = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
        if template is None:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        _validate_content(template["template_key"], body.content)
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE template_id = ?", (prompt_id,)
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO prompt_versions(template_id, version, content, status) VALUES (?, ?, ?, 'draft')",
            (prompt_id, version, body.content),
        )
        _admin_audit(conn, "admin_prompt_version_create", admin[0],
                     {"prompt_id": prompt_id, "version_id": cursor.lastrowid, "version": version})
        return {"id": cursor.lastrowid, "template_id": prompt_id, "version": version,
                "content": body.content, "status": "draft"}


def _find_version(conn, version_id: int):
    row = conn.execute(
        "SELECT pv.*, pt.template_key, pt.program_id FROM prompt_versions pv "
        "JOIN prompt_templates pt ON pt.id = pv.template_id WHERE pv.id = ?", (version_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return row


def _activate(conn, version, expected_id: int | None, change_note: str, actor: int,
              *, rollback_from: int | None = None, previous_active_id: int | None = None) -> tuple[int, int | None]:
    current = conn.execute(
        "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'",
        (version["template_id"],),
    ).fetchone()
    current_id = current["id"] if current else None
    if current_id != expected_id:
        raise HTTPException(status_code=409, detail="Active prompt version has changed")
    if version["status"] not in {"draft", "archived"}:
        raise HTTPException(status_code=409, detail="Prompt version is already active")
    if current_id is not None:
        conn.execute("UPDATE prompt_versions SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (current_id,))
    conn.execute("UPDATE prompt_versions SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (version["id"],))
    event_payload = {
        "template_id": version["template_id"], "new_version_id": version["id"],
        "previous_active_version_id": current_id, "rollback_from_version_id": rollback_from,
        "change_note": change_note,
    }
    audit_id = _admin_audit(conn, "admin_prompt_rollback" if rollback_from else "admin_prompt_activate", actor, event_payload)
    conn.execute(
        "INSERT INTO prompt_version_audit_events(audit_log_id, template_id, action, "
        "source_version_id, previous_active_version_id, new_version_id, change_note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (audit_id, version["template_id"], "rollback" if rollback_from else "activate",
         rollback_from, previous_active_id if rollback_from else current_id, version["id"], change_note),
    )
    return version["id"], current_id


@router.post("/prompts/versions/{version_id}/activate")
def activate_prompt_version(version_id: int, body: ActivationInput, admin: AdminContext) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        version = _find_version(conn, version_id)
        _validate_content(version["template_key"], version["content"])
        _, previous = _activate(conn, version, body.expected_active_version_id, body.change_note, admin[0])
        return {"id": version_id, "status": "active", "previous_active_version_id": previous}


@router.post("/prompts/versions/{version_id}/rollback")
def rollback_prompt_version(version_id: int, body: RollbackInput, admin: AdminContext) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = _find_version(conn, version_id)
        _validate_content(source["template_key"], source["content"])
        active = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (source["template_id"],)
        ).fetchone()
        active_id = active["id"] if active else None
        if active_id != body.expected_active_version_id:
            raise HTTPException(status_code=409, detail="Active prompt version has changed")
        if source["status"] == "active":
            raise HTTPException(status_code=409, detail="Rollback source must be an archived version")
        next_version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE template_id = ?",
            (source["template_id"],),
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO prompt_versions(template_id, version, content, status) VALUES (?, ?, ?, 'draft')",
            (source["template_id"], next_version, source["content"]),
        )
        new_version = _find_version(conn, cursor.lastrowid)
        _, previous = _activate(
            conn, new_version, active_id, body.change_note, admin[0],
            rollback_from=version_id, previous_active_id=active_id,
        )
        return {"id": cursor.lastrowid, "version": next_version, "status": "active",
                "rollback_from_version_id": version_id, "previous_active_version_id": previous}


@router.post("/prompts/versions/{version_id}/render")
def render_prompt_version(version_id: int, body: RenderInput, _: AdminContext) -> dict:
    summaries = _episode_summaries(body.episode_id)
    with get_db_connection() as conn:
        version = _find_version(conn, version_id)
    definition = _get_definition(version["template_key"])
    return {"version_id": version_id, "episode_id": body.episode_id,
            "template_key": version["template_key"], "prompt": _render(version, definition, summaries)}


@router.post("/programs/{program_id}/preview-prompt")
def preview_prompt(program_id: str, body: PreviewInput, admin: AdminContext) -> dict:
    definition = _get_definition(body.template_key)
    summaries = _episode_summaries(body.episode_id)
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM programs WHERE id = ?", (program_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Program not found")
        version = conn.execute(
            "SELECT pv.* FROM prompt_templates pt JOIN prompt_versions pv ON pv.template_id = pt.id "
            "WHERE pt.template_key = ? AND pv.status = 'active' "
            "AND (pt.program_id = ? OR pt.program_id IS NULL) "
            "ORDER BY CASE WHEN pt.program_id = ? THEN 0 ELSE 1 END LIMIT 1",
            (body.template_key, program_id, program_id),
        ).fetchone()
        if version is None:
            raise HTTPException(status_code=404, detail="Active prompt version not found")
        _admin_audit(conn, "admin_prompt_preview", admin[0],
                     {"program_id": program_id, "template_key": body.template_key,
                      "episode_id": body.episode_id, "version_id": version["id"]})
    return {"program_id": program_id, "episode_id": body.episode_id,
            "template_key": body.template_key, "version_id": version["id"],
            "prompt": _render(version, definition, summaries)}
