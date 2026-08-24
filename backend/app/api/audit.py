"""管理者セッション専用の生成監査ログ閲覧API。"""

from datetime import datetime
from typing import Annotated

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import require_owner_session
from app.db.connection import get_db_connection
from app.services.llm_call_log_service import get_llm_call, list_llm_call_metadata, llm_jsonl_path

router = APIRouter(tags=["admin-audit"])

AUDIT_REASON_CODES = {
    "invalid_idempotency_key",
    "idempotency_key_input_mismatch",
    "active_limit",
    "ip_active_limit",
    "global_active_limit",
    "daily_limit",
    "ip_daily_limit",
    "global_daily_limit",
}


def _utc_iso(value: str | None) -> str | None:
    """SQLite の UTC 日時を API 契約の ISO 8601 形式へ正規化する。"""
    if value is None:
        return None
    normalized = value.replace(" ", "T")
    if normalized.endswith("Z") or "+" in normalized[10:] or normalized.endswith("+00:00"):
        return normalized
    return f"{normalized}+00:00"


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    """開始・終了が揃う監査ログだけ、保存値の代わりに経過時間を返す。"""
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(_utc_iso(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(_utc_iso(ended_at).replace("Z", "+00:00"))
        return int((end - start).total_seconds() * 1000)
    except ValueError:
        return None


def _timeline_sort_key(event: dict) -> tuple[str, int, int]:
    return (event["occurred_at"] or "", 0 if event["source"] == "audit" else 1, event["source_id"])


def _audit_reason(value: str | None) -> str | None:
    """監査ログの任意文字列を運用用の定型コードだけに限定する。"""
    return value if value in AUDIT_REASON_CODES else None


def _wav_file_name(value: str | None) -> str | None:
    """応答へサーバー内のファイルパスを含めない。"""
    if value and "/" not in value and "\\" not in value:
        return value
    return None


@router.get("/admin/audit-logs", summary="生成監査ログを取得")
def list_audit_logs(
    _: Annotated[int, Depends(require_owner_session)],
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    """管理者セッション利用者だけに監査情報を返す（秘密値はハッシュのみ）。"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, operation, actor_user_id, episode_id, idempotency_key_hash, input_hash, "
            "accepted, result, rejection_reason, started_at, ended_at "
            "FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/admin/episodes/{episode_id}/logs", summary="エピソードの生成詳細ログを取得")
def get_episode_generation_logs(
    episode_id: int,
    _: Annotated[int, Depends(require_owner_session)],
    phase_log_id: int | None = Query(None, ge=1),
) -> dict:
    """管理画面向けに監査・工程・行ログを1つの読み取り専用応答へ統合する。"""
    with get_db_connection() as conn:
        episode = conn.execute(
            "SELECT id, episode_date, seq, status, type, created_at, updated_at "
            "FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")

        jobs = conn.execute(
            "SELECT j.id, j.operation, u.id AS owner_id, u.username AS owner_username, "
            "j.client_ip_hash, j.status, j.claimed_at, j.finished_at "
            "FROM generation_jobs AS j "
            "JOIN admin_users AS u ON u.id = j.owner_user_id "
            "WHERE j.episode_id = ? ORDER BY j.claimed_at ASC, j.id ASC",
            (episode_id,),
        ).fetchall()
        audit_rows = conn.execute(
            "SELECT id, generation_job_id, operation, result, rejection_reason, started_at, ended_at, executed_at "
            "FROM audit_logs WHERE episode_id = ? "
            "OR generation_job_id IN (SELECT id FROM generation_jobs WHERE episode_id = ?)",
            (episode_id, episode_id),
        ).fetchall()
        phase_rows = conn.execute(
            "SELECT id, generation_job_id, phase, attempt_no, result, started_at, ended_at, "
            "duration_ms, failure_reason, tts_engine, line_success_count, line_total_count, created_at "
            "FROM episode_generation_phase_logs WHERE episode_id = ?",
            (episode_id,),
        ).fetchall()
        llm_rows = [
            {**row, "created_at": _utc_iso(row["created_at"])}
            for row in list_llm_call_metadata(conn, episode_id)
        ]

        selected_phase_id: int | None
        if phase_log_id is not None:
            selected = conn.execute(
                "SELECT id FROM episode_generation_phase_logs "
                "WHERE id = ? AND episode_id = ? AND phase = 'synthesize'",
                (phase_log_id, episode_id),
            ).fetchone()
            if selected is None:
                raise HTTPException(status_code=404, detail="Synthesis phase log not found")
            selected_phase_id = selected["id"]
        else:
            selected = conn.execute(
                "SELECT id FROM episode_generation_phase_logs "
                "WHERE episode_id = ? AND phase = 'synthesize' "
                "ORDER BY attempt_no DESC, id DESC LIMIT 1",
                (episode_id,),
            ).fetchone()
            selected_phase_id = selected["id"] if selected else None

        line_rows = []
        if selected_phase_id is not None:
            line_rows = conn.execute(
                "SELECT l.phase_log_id, p.attempt_no, l.script_line_index, i.article_id, "
                "l.speaker, l.section, l.delivery, l.tts_engine, l.speaking_rate, "
                "l.processing_duration_ms, l.synth_result, l.retry_count, l.wav_file, "
                "l.silence_before_sec, l.start_time_sec, l.failure_reason "
                "FROM episode_generation_line_logs AS l "
                "JOIN episode_generation_phase_logs AS p ON p.id = l.phase_log_id "
                "LEFT JOIN episode_items AS i ON i.episode_id = l.episode_id "
                "AND i.item_order = l.script_line_index "
                "WHERE l.phase_log_id = ? AND l.episode_id = ? "
                "ORDER BY l.script_line_index ASC",
                (selected_phase_id, episode_id),
            ).fetchall()

    timeline = []
    for row in audit_rows:
        occurred_at = row["started_at"] or row["executed_at"]
        timeline.append({
            "source": "audit", "source_id": row["id"],
            "generation_job_id": row["generation_job_id"], "operation": row["operation"],
            "phase": None, "attempt_no": None, "result": row["result"],
            "occurred_at": _utc_iso(occurred_at), "started_at": _utc_iso(row["started_at"]),
            "ended_at": _utc_iso(row["ended_at"]),
            "duration_ms": _duration_ms(row["started_at"], row["ended_at"]),
            "reason": _audit_reason(row["rejection_reason"]), "tts_engine": None,
            "line_success_count": None, "line_total_count": None,
        })
    for row in phase_rows:
        occurred_at = row["started_at"] or row["created_at"]
        timeline.append({
            "source": "phase", "source_id": row["id"],
            "generation_job_id": row["generation_job_id"], "operation": None,
            "phase": row["phase"], "attempt_no": row["attempt_no"],
            "result": row["result"] or "incomplete",
            "occurred_at": _utc_iso(occurred_at), "started_at": _utc_iso(row["started_at"]),
            "ended_at": _utc_iso(row["ended_at"]), "duration_ms": row["duration_ms"],
            "reason": row["failure_reason"], "tts_engine": row["tts_engine"],
            "line_success_count": row["line_success_count"], "line_total_count": row["line_total_count"],
        })
    for row in llm_rows:
        timeline.append({
            "source": "llm", "source_id": row["id"], "call_id": row["call_id"],
            "generation_job_id": None, "operation": None, "phase": row["phase"],
            "attempt_no": row["attempt"], "result": row["status"],
            "occurred_at": _utc_iso(row["created_at"]), "started_at": _utc_iso(row["created_at"]),
            "ended_at": None, "duration_ms": row["latency_ms"], "reason": None,
            "tts_engine": None, "line_success_count": None, "line_total_count": None,
            "model": row["model"], "provider": row["provider"],
        })
    timeline.sort(key=_timeline_sort_key)

    return {
        "episode": {**dict(episode), "created_at": _utc_iso(episode["created_at"]), "updated_at": _utc_iso(episode["updated_at"])},
        "generation_jobs": [
            {"id": row["id"], "operation": row["operation"],
             "owner": {"id": row["owner_id"], "username": row["owner_username"]},
             "client_ip_hash": row["client_ip_hash"], "status": row["status"],
             "claimed_at": _utc_iso(row["claimed_at"]), "finished_at": _utc_iso(row["finished_at"])}
            for row in jobs
        ],
        "timeline": timeline,
        # 本文は含めず、必要な1件だけ詳細APIで取得する。
        "llm_calls": llm_rows,
        "lines": [{**dict(row), "wav_file": _wav_file_name(row["wav_file"])} for row in line_rows],
    }


@router.get("/admin/episodes/{episode_id}/llm-calls", summary="LLM呼び出し一覧を取得")
def list_episode_llm_calls(
    episode_id: int,
    _: Annotated[int, Depends(require_owner_session)],
    limit: int = Query(500, ge=1, le=2000),
) -> dict:
    """LLM本文を含めないメタ情報一覧。"""
    with get_db_connection() as conn:
        episode = conn.execute("SELECT id FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")
        calls = list_llm_call_metadata(conn, episode_id, limit)
    return {"episode_id": episode_id, "calls": calls, "total": len(calls)}


def _llm_jsonl_response(episode_id: int) -> Response:
    with get_db_connection() as conn:
        episode = conn.execute("SELECT id FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")
        rows = conn.execute(
            "SELECT call_id, episode_id, phase, provider, model, base_url, attempt, status, "
            "latency_ms, prompt_text, response_text, thinking_text, created_at "
            "FROM llm_call_logs WHERE episode_id = ? ORDER BY created_at ASC, id ASC",
            (episode_id,),
        ).fetchall()
    jsonl_path = llm_jsonl_path(episode_id)
    if jsonl_path.is_file():
        # DB障害時もbest-effortで残ったエピソード別ファイルを取得できる。
        body = jsonl_path.read_text(encoding="utf-8")
    else:
        body = "".join(json.dumps(dict(row), ensure_ascii=False) + "\n" for row in rows)
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="episode-{episode_id}-llm-calls.jsonl"'},
    )


@router.get("/admin/episodes/{episode_id}/llm-calls/download", summary="LLM呼び出しJSONLをダウンロード")
def download_episode_llm_calls(
    episode_id: int,
    _: Annotated[int, Depends(require_owner_session)],
) -> Response:
    return _llm_jsonl_response(episode_id)


@router.get("/admin/episodes/{episode_id}/llm-calls.jsonl", summary="LLM呼び出しJSONLをダウンロード")
def download_episode_llm_calls_legacy(
    episode_id: int,
    _: Annotated[int, Depends(require_owner_session)],
) -> Response:
    return _llm_jsonl_response(episode_id)


@router.get("/admin/episodes/{episode_id}/llm-calls/{call_id}", summary="LLM呼び出し本文を取得")
def get_episode_llm_call(
    episode_id: int,
    call_id: str,
    _: Annotated[int, Depends(require_owner_session)],
) -> dict:
    with get_db_connection() as conn:
        item = get_llm_call(conn, episode_id, call_id)
    if item is None:
        raise HTTPException(status_code=404, detail="LLM call not found")
    return item
