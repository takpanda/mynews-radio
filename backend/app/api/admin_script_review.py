"""台本確認待ちepisodeの管理API。"""

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import require_owner_session
from app.batch.final_validation import validate_final_script
from app.programs.profiles import get_profile_by_id
from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.generation_control import dispatch_job, input_hash
from app.audit import hash_value

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-script-review"])


class ScriptUpdate(BaseModel):
    revision: int = Field(ge=1)
    script: dict


class RejectRequest(BaseModel):
    action: str = Field(pattern="^(regenerate|discard)$")


def _script_path(episode_id: int) -> Path:
    root = Path(os.environ.get("EPISODES_DIR", "data/episodes")).resolve()
    path = (root / str(episode_id) / "script.json").resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid episode path")
    return path


def _latest_revision(conn, episode_id: int):
    return conn.execute(
        "SELECT revision, script_json, source, actor_user_id, created_at FROM script_revisions "
        "WHERE episode_id = ? ORDER BY revision DESC LIMIT 1", (episode_id,),
    ).fetchone()


def _ensure_initial_revision(conn, episode_id: int, source: str = "generated"):
    row = _latest_revision(conn, episode_id)
    if row:
        return row
    path = _script_path(episode_id)
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Script not found") from exc
    conn.execute(
        "INSERT OR IGNORE INTO script_revisions(episode_id, revision, script_json, source) VALUES (?, 1, ?, ?)",
        (episode_id, json.dumps(script, ensure_ascii=False), source),
    )
    return _latest_revision(conn, episode_id)


def _audit(conn, operation: str, user_id: int, episode_id: int, payload: object, result="success"):
    digest = input_hash(payload)
    conn.execute(
        "INSERT INTO audit_logs(operation, owner_user_id, actor_user_id, input_hash, executed_at, result, accepted, episode_id) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, 1, ?)",
        (operation, user_id, user_id, digest, result, episode_id),
    )


def _enqueue_episode_job(conn, *, user_id: int, operation: str, episode_id: int, payload: dict) -> tuple[int, str]:
    """既存の生成FIFOへepisode単位のジョブを登録する。呼び出し側transaction内で実行。"""
    active = conn.execute("SELECT 1 FROM generation_jobs WHERE status IN ('active','waiting') LIMIT 1").fetchone()
    status = "waiting" if active else "active"
    key = f"script-review-{operation}-{episode_id}-{uuid.uuid4().hex}"
    digest = input_hash(payload)
    cursor = conn.execute(
        "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, client_ip_hash, episode_id, payload, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, operation, key, digest, hash_value("admin-script-review"), episode_id,
         json.dumps(payload, ensure_ascii=False), status),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO audit_logs(operation, owner_user_id, actor_user_id, generation_job_id, input_hash, executed_at, result, accepted, started_at, episode_id) "
        "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'started', 1, CASE WHEN ?='active' THEN CURRENT_TIMESTAMP ELSE NULL END, ?)",
        (operation, user_id, user_id, job_id, digest, status, episode_id),
    )
    return job_id, status


@router.get("/admin/episodes")
def list_admin_episodes(
    _: Annotated[int, Depends(require_owner_session)], status: str | None = None,
) -> list[dict]:
    query = "SELECT id, episode_date, seq, status, phase, generation_message, review_mode, updated_at FROM episodes"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY episode_date DESC, seq DESC, id DESC LIMIT 200"
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


@router.get("/admin/episodes/{episode_id}/script")
def get_script(episode_id: int, _: Annotated[int, Depends(require_owner_session)]) -> dict:
    with get_db_connection() as conn:
        episode = conn.execute(
            "SELECT program_snapshot FROM episodes WHERE id=?", (episode_id,),
        ).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        row = _ensure_initial_revision(conn, episode_id)
        snapshot = json.loads(episode["program_snapshot"]) if episode["program_snapshot"] else None
        cast = [
            {key: member[key] for key in ("key", "name", "role")}
            for member in snapshot["cast"]
        ] if snapshot is not None else None
        return {
            "episode_id": episode_id,
            "revision": row["revision"],
            "script": json.loads(row["script_json"]),
            "cast": cast,
        }


@router.put("/admin/episodes/{episode_id}/script")
def put_script(episode_id: int, body: ScriptUpdate, user_id: Annotated[int, Depends(require_owner_session)]) -> dict:
    if not isinstance(body.script.get("lines"), list):
        raise HTTPException(status_code=422, detail="script.lines must be an array")
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        episode = conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode["status"] != "awaiting_review":
            raise HTTPException(status_code=409, detail="Episode is not awaiting review")
        current = _ensure_initial_revision(conn, episode_id)
        if current["revision"] != body.revision:
            raise HTTPException(status_code=409, detail={"message": "Script revision conflict", "latest_revision": current["revision"]})
        next_revision = current["revision"] + 1
        encoded = json.dumps(body.script, ensure_ascii=False)
        conn.execute(
            "INSERT INTO script_revisions(episode_id, revision, script_json, source, actor_user_id) VALUES (?, ?, ?, 'human', ?)",
            (episode_id, next_revision, encoded, user_id),
        )
        conn.execute("UPDATE episodes SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (episode_id,))
        _audit(conn, "script_update", user_id, episode_id, {"revision": next_revision})
    _script_path(episode_id).write_text(json.dumps(body.script, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"episode_id": episode_id, "revision": next_revision, "script": body.script}


@router.get("/admin/episodes/{episode_id}/script/revisions")
def list_script_revisions(episode_id: int, _: Annotated[int, Depends(require_owner_session)]) -> list[dict]:
    with get_db_connection() as conn:
        if not conn.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Episode not found")
        _ensure_initial_revision(conn, episode_id)
        rows = conn.execute(
            "SELECT revision, script_json, source, actor_user_id, created_at FROM script_revisions WHERE episode_id=? ORDER BY revision DESC",
            (episode_id,),
        ).fetchall()
        return [
            {"revision": row["revision"], "script": json.loads(row["script_json"]),
             "source": row["source"], "actor_user_id": row["actor_user_id"], "created_at": row["created_at"]}
            for row in rows
        ]


def _validate_episode_script(episode_id: int, script: dict) -> dict:
    summaries = []
    try:
        value = json.loads((_script_path(episode_id).parent / "summaries.json").read_text(encoding="utf-8"))
        if isinstance(value, list):
            summaries = [item for item in value if isinstance(item, dict)]
    except (OSError, ValueError):
        pass
    profile_id = script.get("program_profile_id")
    profile = get_profile_by_id(str(profile_id)) if profile_id else None
    result = validate_final_script(
        script.get("lines", []), summaries=summaries,
        program_name=str(script.get("program_name") or "ニュースのとなり"),
        style=script.get("style", "dialogue"), program_profile=profile,
    )
    findings = [
        {**item, "severity": "error"} for item in result.get("critical_issues", [])
    ] + [{**item, "severity": "warning"} for item in result.get("warnings", [])]
    return {"can_approve": not any(item["severity"] == "error" for item in findings), "results": findings}


@router.post("/admin/episodes/{episode_id}/validate")
def validate_script(episode_id: int, user_id: Annotated[int, Depends(require_owner_session)]) -> dict:
    with get_db_connection() as conn:
        episode = conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode["status"] != "awaiting_review":
            raise HTTPException(status_code=409, detail="Episode is not awaiting review")
        row = _ensure_initial_revision(conn, episode_id)
        revision = row["revision"]
        script = json.loads(row["script_json"])
    result = _validate_episode_script(episode_id, script)
    result["revision"] = revision
    with get_db_connection() as conn:
        _audit(conn, "script_validate", user_id, episode_id, {"revision": revision})
    return result


@router.post("/admin/episodes/{episode_id}/approve")
def approve_script(episode_id: int, user_id: Annotated[int, Depends(require_owner_session)]) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        episode = conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        row = _ensure_initial_revision(conn, episode_id)
        script = json.loads(row["script_json"])
        validation = _validate_episode_script(episode_id, script)
        if not validation["can_approve"]:
            raise HTTPException(status_code=409, detail={"message": "Script has validation errors", **validation})
        old_job = conn.execute(
            "SELECT id, status FROM generation_jobs WHERE episode_id=? AND operation='synthesize' "
            "AND status IN ('active','waiting','completed') ORDER BY id DESC LIMIT 1", (episode_id,),
        ).fetchone()
        if old_job:
            return {"episode_id": episode_id, "status": episode["status"], "job_id": old_job["id"]}
        if episode["status"] != "awaiting_review":
            raise HTTPException(status_code=409, detail="Episode is not awaiting review")
        script_path = _script_path(episode_id)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        job_id, job_status = _enqueue_episode_job(conn, user_id=user_id, operation="synthesize", episode_id=episode_id, payload={})
        conn.execute("UPDATE episodes SET status='synthesizing', phase='synthesize', updated_at=CURRENT_TIMESTAMP WHERE id=?", (episode_id,))
        _audit(conn, "script_approve", user_id, episode_id, {"revision": row["revision"]})
    if job_status == "active":
        dispatch_job(job_id)
    return {"episode_id": episode_id, "status": "synthesizing", "job_id": job_id}


@router.post("/admin/episodes/{episode_id}/reject")
def reject_script(episode_id: int, body: RejectRequest, user_id: Annotated[int, Depends(require_owner_session)]) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT episode_date, seq, status FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Episode not found")
        if row["status"] != "awaiting_review":
            raise HTTPException(status_code=409, detail="Episode is not awaiting review")
        if body.action == "discard":
            conn.execute("UPDATE episodes SET status='discarded', phase='discarded', updated_at=CURRENT_TIMESTAMP WHERE id=?", (episode_id,))
            _audit(conn, "script_discard", user_id, episode_id, {})
            return {"episode_id": episode_id, "status": "discarded"}
        payload = {"date": row["episode_date"], "news_source": "hatena_bookmark", "tts_engine": get_settings().batch_default_tts_engine}
        job_id, job_status = _enqueue_episode_job(conn, user_id=user_id, operation="daily", episode_id=episode_id, payload=payload)
        conn.execute("UPDATE episodes SET status='generating', phase='generate_script', updated_at=CURRENT_TIMESTAMP WHERE id=?", (episode_id,))
        _audit(conn, "script_regenerate", user_id, episode_id, {"job_id": job_id})
    if job_status == "active":
        dispatch_job(job_id)
    return {"episode_id": episode_id, "status": "generating", "job_id": job_id}


@router.post("/admin/episodes/{episode_id}/lines/{idx}/preview-audio")
def preview_audio(episode_id: int, idx: int, user_id: Annotated[int, Depends(require_owner_session)]) -> FileResponse:
    # Preview synthesis is intentionally not persisted as delivery audio.
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Episode not found")
        limits = conn.execute(
            "SELECT SUM(CASE WHEN admin_user_id=? AND created_at >= datetime('now','-1 minute') THEN 1 ELSE 0 END) AS user_count, "
            "SUM(CASE WHEN episode_id=? AND created_at >= datetime('now','-1 day') THEN 1 ELSE 0 END) AS episode_count "
            "FROM script_preview_rate_limits", (user_id, episode_id),
        ).fetchone()
        if (limits["user_count"] or 0) >= 5 or (limits["episode_count"] or 0) >= 30:
            raise HTTPException(status_code=429, detail="Preview audio rate limit exceeded")
        conn.execute("INSERT INTO script_preview_rate_limits(admin_user_id, episode_id) VALUES (?, ?)", (user_id, episode_id))
        row = _ensure_initial_revision(conn, episode_id)
        script = json.loads(row["script_json"])
    lines = script.get("lines", [])
    if idx < 0 or idx >= len(lines):
        raise HTTPException(status_code=404, detail="Script line not found")
    line = lines[idx]
    text = str(line.get("spoken_text") or line.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Script line has no speakable text")
    settings = get_settings()
    engine = settings.default_tts_engine
    if engine == "fishs2pro":
        from app.services.fishs2pro_client import FishS2ProClient
        from app.services.settings_service import resolve_tts_speakers
        male, female = resolve_tts_speakers(engine)
        client = FishS2ProClient(settings.fishs2pro_base_url, voice_male=male, voice_female=female)
        speaker = "female" if str(line.get("speaker", "male")).lower() in {"female", "woman", "f"} else "male"
    else:
        from app.services.voicevox_client import VoicevoxClient
        from app.services.settings_service import resolve_tts_speakers
        base_url = settings.aivispeech_base_url if engine == "aivispeech" else settings.voicevox_base_url
        male, female = resolve_tts_speakers(engine)
        client = VoicevoxClient(base_url, speaker_male=male, speaker_female=female)
        speaker = "female" if str(line.get("speaker", "male")).lower() in {"female", "woman", "f"} else "male"
    fd, temp_path = tempfile.mkstemp(prefix="script-preview-", suffix=".wav")
    os.close(fd)
    try:
        ok = client.synthesize_line(text, speaker, temp_path)
    except Exception:
        logger.warning("script preview synthesis failed: episode_id=%d line=%d", episode_id, idx)
        Path(temp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="Preview audio synthesis failed")
    finally:
        close = getattr(client, "close", None)
        if close:
            close()
    if not ok:
        Path(temp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="Preview audio synthesis failed")
    return FileResponse(temp_path, media_type="audio/wav", filename="preview.wav", background=BackgroundTask(Path(temp_path).unlink, missing_ok=True))
