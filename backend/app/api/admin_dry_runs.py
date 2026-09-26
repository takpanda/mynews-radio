"""管理画面向けの非同期台本 dry-run API。"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_admin_with_token
from app.db.connection import get_db_connection
from app.programs.serialization import (
    load_program_profile,
    program_profile_from_definition,
    program_profile_to_definition,
)
from app.services.generation_control import GenerationControlError, enqueue_job, dispatch_job
from app.services.article_service import ArticleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-dry-runs"])
AdminContext = Annotated[tuple[int, str], Depends(require_admin_with_token)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DryRunInput(StrictModel):
    draft_program_definition: dict | None = None
    draft_prompt_version_id: int | None = Field(default=None, ge=1)
    input_episode_id: int | None = Field(default=None, ge=1)


def _get_input_summaries(program_id: str, input_episode_id: int | None) -> list[dict]:
    if input_episode_id is not None:
        return _load_episode_summaries(input_episode_id)

    with get_db_connection() as conn:
        row = conn.execute("SELECT definition FROM programs WHERE id=? AND is_active=1", (program_id,)).fetchone()
    if row is None:
        raise ValueError("番組が見つからないか無効です")
    settings_module = __import__("app.services.settings_service", fromlist=["get_settings_or_default"])
    settings = settings_module.get_settings_or_default()
    from app.api.generate import RADIO_PROGRAM_NEWS_SOURCES
    news_source = RADIO_PROGRAM_NEWS_SOURCES.get(program_id, "hatena_hotentry_all")
    from app.batch.summarize_articles import summarize_articles
    with tempfile.TemporaryDirectory(prefix="dry-run-summaries-") as tmp:
        summarize_articles(
            str(Path(tmp) / "summaries.json"), news_source=news_source, program_id=program_id,
        )
    return ArticleService().fetch_summaries_for_script(
        max_articles=int(os.getenv("MAX_SCRIPT_ARTICLES", "8")),
        min_importance_score=int(os.getenv("MIN_IMPORTANCE_SCORE", "1")),
        source=news_source,
        priority_themes=settings.priority_themes,
        excluded_themes=settings.excluded_themes,
    )


def _load_episode_summaries(input_episode_id: int) -> list[dict]:
    from app.api.admin_prompts import EPISODES_DIR
    path = EPISODES_DIR / str(input_episode_id) / "summaries.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("指定エピソードの summaries.json が読み取れません") from exc
    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
        raise ValueError("指定エピソードの summaries.json が不正です")
    for item in value:
        if "id" not in item:
            item["id"] = item.get("article_id")
        if not isinstance(item.get("id"), (int, str)) or not isinstance(item.get("summary"), str):
            raise ValueError("summaries.json の記事要約または記事IDが不正です")
    return value


def _validate_draft_prompt(program_id: str, version_id: int | None) -> None:
    if version_id is None:
        return
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT pv.id FROM prompt_versions pv JOIN prompt_templates pt ON pt.id=pv.template_id "
            "WHERE pv.id=? AND pv.status='draft' AND pt.template_key='generate_radio_script' "
            "AND (pt.program_id=? OR pt.program_id IS NULL)",
            (version_id, program_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail="下書きプロンプト版が番組に適用できません")


@router.post("/programs/{program_id}/dry-run", status_code=202)
def create_dry_run(
    program_id: str,
    body: DryRunInput,
    request: Request,
    admin: AdminContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    with get_db_connection() as conn:
        current = load_program_profile(conn, program_id)
        if current is None or current.kind != "radio":
            raise HTTPException(status_code=404, detail="Radio program not found")
        mc_ids = {member.mc_id for member in current.cast if member.mc_id}
        for mc_id in mc_ids:
            mc = conn.execute("SELECT is_active FROM mc_profiles WHERE id=?", (mc_id,)).fetchone()
            if mc is None or not mc["is_active"]:
                raise HTTPException(status_code=422, detail=f"Unknown or inactive MC: {mc_id}")

    draft = current
    if body.draft_program_definition is not None:
        try:
            from app.api.admin_programs import ProgramFields, _profile, _validate_mc_references
            draft_input = ProgramFields.model_validate(body.draft_program_definition)
            draft = _profile(draft_input)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if draft.id != program_id:
            raise HTTPException(status_code=422, detail="番組定義の id は対象番組と一致させてください")
        if draft.kind != "radio":
            raise HTTPException(status_code=422, detail="dry-run は radio 番組のみ対応します")
        with get_db_connection() as conn:
            _validate_mc_references(conn, draft)
    _validate_draft_prompt(program_id, body.draft_prompt_version_id)
    if body.input_episode_id is not None:
        try:
            _load_episode_summaries(body.input_episode_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = {
        "program_id": program_id,
        "current_definition": program_profile_to_definition(current),
        "draft_definition": program_profile_to_definition(draft) if body.draft_program_definition is not None else None,
        "draft_prompt_version_id": body.draft_prompt_version_id,
        "input_episode_id": body.input_episode_id,
    }
    try:
        claim = enqueue_job(
            admin[0], "dry_run", idempotency_key or "", payload,
            client_ip=request.client.host if request.client else "unknown", dispatch=False,
        )
    except GenerationControlError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    if not claim.duplicate:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO dry_runs(id, program_id, program_definition, draft_program_definition, "
                "prompt_version_id, input_episode_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (claim.job_id, program_id, json.dumps(payload["current_definition"], ensure_ascii=False),
                 json.dumps(payload["draft_definition"], ensure_ascii=False) if payload["draft_definition"] else None,
                 body.draft_prompt_version_id, body.input_episode_id,
                 "running" if claim.status == "active" else "queued"),
            )
        dispatch_job(claim.job_id)
    status = {"active": "running", "waiting": "queued"}.get(claim.status, claim.status)
    return {"id": claim.job_id, "status": status}


def execute_dry_run(dry_run_id: int, payload: dict) -> bool:
    with get_db_connection() as conn:
        conn.execute("UPDATE dry_runs SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?", (dry_run_id,))
    try:
        summaries = _get_input_summaries(payload["program_id"], payload.get("input_episode_id"))
        if not summaries:
            raise ValueError("台本生成に使える記事要約がありません")
        current = program_profile_from_definition(payload["current_definition"])
        draft = (
            program_profile_from_definition(payload["draft_definition"])
            if payload.get("draft_definition") else current
        )
        scripts = {}
        validations = {}
        for name, profile, version in (
            ("current", current, None),
            ("draft", draft, payload.get("draft_prompt_version_id")),
        ):
            if name == "draft" and payload.get("draft_definition") is None and version is None:
                continue
            from app.batch.generate_script import generate_script
            from app.batch.final_validation import validate_final_script_file
            with tempfile.TemporaryDirectory(prefix="dry-run-") as tmp:
                path = Path(tmp) / "script.json"
                summaries_path = Path(tmp) / "summaries.json"
                summaries_path.write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")
                generate_script(
                    str(path), program_name=profile.name, news_source=None,
                    program_profile=profile, summaries_override=summaries,
                    prompt_version_id=version, mark_articles=False, use_program_prompt_scope=True,
                )
                if not path.exists():
                    raise ValueError("台本を生成できませんでした")
                validation = validate_final_script_file(
                    str(path), summaries_path=str(summaries_path), output_dir=tmp,
                    program_name=profile.name, program_profile=profile,
                )
                script = json.loads(path.read_text(encoding="utf-8"))
            scripts[name] = script
            validations[name] = [
                {**issue, "severity": severity}
                for severity, key in (("error", "critical_issues"), ("warning", "warnings"))
                for issue in validation.get(key, [])
            ]
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE dry_runs SET status='completed', script_json=?, validation_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(scripts, ensure_ascii=False), json.dumps(validations, ensure_ascii=False), dry_run_id),
            )
        return True
    except Exception as exc:
        logger.exception("dry-run failed: id=%d", dry_run_id)
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE dry_runs SET status='failed', error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(exc)[:500], dry_run_id),
            )
        return False


def _dry_run_row(row) -> dict:
    result = dict(row)
    for key in ("program_definition", "draft_program_definition", "script_json", "validation_json"):
        result[key] = json.loads(result[key]) if result.get(key) else None
    return result


@router.get("/dry-runs")
def list_dry_runs(_: AdminContext, status: str | None = Query(default=None)) -> list[dict]:
    if status is not None and status not in {"queued", "running", "completed", "failed"}:
        raise HTTPException(status_code=422, detail="Invalid dry-run status")
    query = "SELECT * FROM dry_runs"
    params = ()
    if status:
        query += " WHERE status=?"
        params = (status,)
    query += " ORDER BY id DESC LIMIT 100"
    with get_db_connection() as conn:
        return [_dry_run_row(row) for row in conn.execute(query, params).fetchall()]


@router.get("/dry-runs/{dry_run_id}")
def get_dry_run(dry_run_id: int, _: AdminContext) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM dry_runs WHERE id=?", (dry_run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Dry-run not found")
    return _dry_run_row(row)
