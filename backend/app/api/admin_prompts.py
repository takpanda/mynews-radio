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


def _episode_data(episode_id: int) -> dict:
    with get_db_connection() as conn:
        episode = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    episode_dir = EPISODES_DIR / str(episode_id)
    data = {"dir": episode_dir}
    for name in ("summaries", "script", "review", "prompt_context"):
        path = episode_dir / "review" / "review.json" if name == "review" else episode_dir / f"{name}.json"
        if not path.exists():
            data[name] = None
            continue
        try:
            data[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=f"Episode {name} data is invalid") from exc
    return data


def _episode_variables(episode_id: int, template_key: str, required: list[str]) -> dict:
    data = _episode_data(episode_id)
    summaries = data["summaries"]
    script = data["script"]
    review = data["review"]
    prompt_context = data["prompt_context"]
    variables: dict = {}

    if template_key in {"generate_radio_script", "generate_narrative_arc"}:
        saved_context = prompt_context if isinstance(prompt_context, dict) else None
        if template_key == "generate_radio_script" and isinstance(saved_context, dict) \
                and set(required).issubset(saved_context):
            variables.update(saved_context)
        elif not isinstance(summaries, list) or not summaries:
            raise HTTPException(status_code=422, detail="Missing required episode input: summaries_json (summaries.json)")
        else:
            episode_script = script if isinstance(script, dict) else {}
        if template_key == "generate_radio_script" and "summaries_json" not in variables:
            # summaries.json holds the episode's summary evidence. Match its IDs to the
            # final script order and hydrate columns that the writer read from articles.
            order = []
            for line in episode_script.get("lines", []):
                article_id = line.get("article_id") if isinstance(line, dict) else None
                if article_id is not None and article_id not in order:
                    order.append(article_id)
            ids = [item.get("id", item.get("article_id")) for item in summaries if isinstance(item, dict)]
            ordered_ids = [article_id for article_id in order if article_id in ids]
            ordered_ids.extend(article_id for article_id in ids if article_id not in ordered_ids)
            with get_db_connection() as conn:
                article_rows = {}
                if ordered_ids:
                    placeholders = ",".join("?" for _ in ordered_ids)
                    article_rows = {row["id"]: dict(row) for row in conn.execute(
                        f"SELECT id, title, source, url, summary, category, importance_score, difficulty "
                        f"FROM articles WHERE id IN ({placeholders})", ordered_ids,
                    ).fetchall()}
            by_id = {item.get("id", item.get("article_id")): item for item in summaries if isinstance(item, dict)}
            hydrated = []
            for article_id in ordered_ids:
                row = article_rows.get(article_id)
                if row is None:
                    raise HTTPException(status_code=422, detail=f"Missing required episode input: article {article_id} (articles)")
                # The DB row is authoritative for the fields used by generate_script.
                hydrated.append(row)
            summaries = hydrated
        if "summaries_json" not in variables:
            variables["summaries_json"] = json.dumps(summaries, ensure_ascii=False, indent=2)
        if isinstance(prompt_context, dict):
            variables.update(prompt_context)
        elif template_key == "generate_radio_script":
            if script and script.get("discussion_article_id") is not None:
                with get_db_connection() as conn:
                    arc_row = conn.execute(
                        "SELECT response_text FROM llm_call_logs WHERE episode_id = ? AND phase = 'arc' "
                        "AND status = 'success' ORDER BY id DESC LIMIT 1", (episode_id,),
                    ).fetchone()
                try:
                    arc = json.loads(arc_row["response_text"]) if arc_row else None
                except (TypeError, json.JSONDecodeError):
                    arc = None
                if not isinstance(arc, dict):
                    raise HTTPException(status_code=422, detail="Missing required episode input: narrative_arc_section (arc result is unavailable)")
                article_ids = [item["id"] for item in summaries]
                article_order = [aid for aid in arc.get("article_order", []) if aid in article_ids]
                article_order.extend(aid for aid in article_ids if aid not in article_order)
                discussion_id = script["discussion_article_id"]
                if discussion_id not in article_order:
                    raise HTTPException(status_code=422, detail="Missing required episode input: narrative arc article order")
                article_order.remove(discussion_id)
                article_order.append(discussion_id)
                arc["article_order"] = article_order
                arc["discussion_article_id"] = discussion_id
                from app.batch.generate_script import _build_narrative_arc_section
                variables["narrative_arc_section"] = _build_narrative_arc_section(arc, summaries)
            else:
                # An arc is only recorded in script.json when one was used.
                variables["narrative_arc_section"] = ""
    elif template_key == "generate_commentary_script":
        if not isinstance(script, dict):
            raise HTTPException(status_code=422, detail="Missing required episode input: script.json")
        article_id = next((line.get("article_id") for line in script.get("lines", [])
                           if isinstance(line, dict) and line.get("article_id") is not None), None)
        article = None
        if article_id is not None:
            with get_db_connection() as conn:
                row = conn.execute("SELECT id, title, text FROM articles WHERE id = ?", (article_id,)).fetchone()
            article = dict(row) if row else None
        if article is None:
            raise HTTPException(status_code=422, detail="Missing required episode input: source article (episode_items/articles)")
        style = script.get("style")
        mc_gender = script.get("mc_gender")
        if not style or not mc_gender:
            raise HTTPException(status_code=422, detail="Missing required episode input: style or mc_gender (script.json)")
        from app.batch.generate_commentary_script import _build_section_details, _calc_suggested_lines
        text_length = len(article.get("text") or "")
        suggested_lines = _calc_suggested_lines(text_length, style)
        variables.update({
            "article_id": article["id"], "article_title": article.get("title") or "",
            "article_json": json.dumps({"id": article["id"], "title": article.get("title") or "",
                                        "text": article.get("text") or ""}, ensure_ascii=False, indent=2),
            "mc_gender": mc_gender, "style": style,
            "section_details": _build_section_details(suggested_lines, style),
            "suggested_lines_count": suggested_lines,
        })
    elif template_key.startswith("review_"):
        if not isinstance(script, dict):
            raise HTTPException(status_code=422, detail="Missing required episode input: script.json")
        original_script_path = data["dir"] / "review" / "original_script.json"
        if original_script_path.is_file():
            try:
                script = json.loads(original_script_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail="Episode original review script is invalid") from exc
        else:
            with get_db_connection() as conn:
                generated_revision = conn.execute(
                    "SELECT script_json FROM script_revisions WHERE episode_id = ? AND source = 'generated' "
                    "ORDER BY revision ASC LIMIT 1", (episode_id,),
                ).fetchone()
            if generated_revision is None:
                raise HTTPException(status_code=422, detail="Missing required episode input: original pre-review script")
            try:
                original_script = json.loads(generated_revision["script_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail="Episode generated script revision is invalid") from exc
            if original_script != script:
                raise HTTPException(status_code=422, detail="Missing required episode input: original pre-review script")
            script = original_script

        article = _episode_review_article(script)
        if isinstance(summaries, list) and summaries:
            evidence = summaries
        elif article is not None:
            evidence = [article]
        else:
            raise HTTPException(status_code=422, detail="Missing required episode input: article_summaries_json (summaries.json or source article)")
        from app.batch.review_script import _format_review_evidence
        evidence_text = _format_review_evidence(evidence)
        script_text = json.dumps(script, ensure_ascii=False, indent=2)
        variables.update({"script_json": script_text, "original_script_json": script_text,
                          "article_summaries_json": evidence_text,
                          "mode": script.get("style", "dialogue"),
                          "mc_gender": script.get("mc_gender", "male")})
        if template_key == "review_radio_director":
            from app.batch.review_script import _build_output_issue_example, _build_radio_director_style_guidance
            style = script.get("style", "")
            variables.update({"style_guidance": _build_radio_director_style_guidance(style),
                              "output_issue_example": _build_output_issue_example(style)})
        if template_key == "review_synthesize":
            reviews = review.get("reviews") if isinstance(review, dict) else None
            if not isinstance(reviews, dict):
                raise HTTPException(status_code=422, detail="Missing required episode input: reviews (review/review.json)")
            for key in ("beginner", "genius", "worried", "positive", "radio"):
                if key not in reviews:
                    raise HTTPException(status_code=422, detail=f"Missing required episode input: reviews.{key} (review/review.json)")
                variables[f"{key}_review"] = json.dumps(reviews[key], ensure_ascii=False, indent=2)
    elif template_key == "category":
        if not isinstance(script, dict) or not isinstance(script.get("lines"), list):
            raise HTTPException(status_code=422, detail="Missing required episode input: script.json lines")
        source = "\n".join(str(line.get("text", "")).strip() for line in script["lines"]
                             if isinstance(line, dict) and str(line.get("text", "")).strip())
        if not source:
            if not isinstance(summaries, list):
                raise HTTPException(status_code=422, detail="Missing required episode input: source (script.json or summaries.json)")
            source = "\n".join(str(item.get("summary", "")).strip() for item in summaries
                                if isinstance(item, dict) and item.get("summary"))
        if not source:
            raise HTTPException(status_code=422, detail="Missing required episode input: source (script.json lines or summaries.json)")
        from app.services.episode_category_service import EPISODE_CATEGORIES
        variables.update({"categories": ", ".join(EPISODE_CATEGORIES), "source": source})
    elif template_key == "summarize_article":
        article_ids = [item.get("id", item.get("article_id")) for item in summaries or []
                       if isinstance(item, dict)]
        with get_db_connection() as conn:
            row = None
            if article_ids:
                row = conn.execute(
                    "SELECT id, title, source, url, text, published_at FROM articles WHERE id = ?",
                    (article_ids[0],),
                ).fetchone()
        if row is None:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT a.id, a.title, a.source, a.url, a.text, a.published_at "
                    "FROM episode_items i JOIN articles a ON a.id = i.article_id "
                    "WHERE i.episode_id = ? ORDER BY i.item_order LIMIT 1", (episode_id,),
                ).fetchone()
        if row is None:
            raise HTTPException(status_code=422, detail="Missing required episode input: source article (episode_items/articles)")
        article = dict(row)
        from app.config import get_settings
        variables.update({key: article.get(key) for key in ("published_at", "source", "title", "url")})
        variables["text"] = (
            (article["text"] or "")[:get_settings().summary_article_max_chars]
            if article.get("text") is not None else None
        )
        missing_article_fields = sorted(
            key for key in required if variables.get(key) is None or variables.get(key) == ""
        )
        if missing_article_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required episode inputs: {', '.join(missing_article_fields)} (articles)",
            )

    missing = sorted(set(required) - variables.keys())
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required episode inputs: {', '.join(missing)}")
    return variables


def _episode_review_article(script: dict) -> dict | None:
    article_id = next((line.get("article_id") for line in script.get("lines", [])
                       if isinstance(line, dict) and line.get("article_id") is not None), None)
    if article_id is None:
        return None
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, title, source, url, text, published_at, summary, category, importance_score, difficulty "
            "FROM articles WHERE id = ?", (article_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def _render(version, definition: dict, episode_id: int) -> str:
    variables = _episode_variables(episode_id, version["template_key"], definition["required_variables"])
    variables = {key: value for key, value in variables.items() if key in definition["allowed_variables"]}
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
        if source["status"] != "archived":
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
    with get_db_connection() as conn:
        version = _find_version(conn, version_id)
    definition = _get_definition(version["template_key"])
    return {"version_id": version_id, "episode_id": body.episode_id,
            "template_key": version["template_key"], "prompt": _render(version, definition, body.episode_id)}


@router.post("/programs/{program_id}/preview-prompt")
def preview_prompt(program_id: str, body: PreviewInput, admin: AdminContext) -> dict:
    definition = _get_definition(body.template_key)
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM programs WHERE id = ?", (program_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Program not found")
        version = conn.execute(
            "SELECT pv.*, pt.template_key FROM prompt_templates pt JOIN prompt_versions pv ON pv.template_id = pt.id "
            "WHERE pt.template_key = ? AND pv.status = 'active' "
            "AND (pt.program_id = ? OR pt.program_id IS NULL) "
            "ORDER BY CASE WHEN pt.program_id = ? THEN 0 ELSE 1 END LIMIT 1",
            (body.template_key, program_id, program_id),
        ).fetchone()
        if version is None:
            raise HTTPException(status_code=404, detail="Active prompt version not found")
    prompt = _render(version, definition, body.episode_id)
    with get_db_connection() as conn:
        _admin_audit(conn, "admin_prompt_preview", admin[0],
                     {"program_id": program_id, "template_key": body.template_key,
                      "episode_id": body.episode_id, "version_id": version["id"]})
    return {"program_id": program_id, "episode_id": body.episode_id,
            "template_key": body.template_key, "version_id": version["id"],
            "prompt": prompt}
