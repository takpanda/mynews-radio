"""管理者セッション専用の運用ダッシュボード集計API。"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.auth import require_owner_session
from app.db.connection import get_db_connection

router = APIRouter(tags=["admin-dashboard"])

RANGE_DAYS = {"7d": 7, "30d": 30}
RECENT_FAILURE_LIMIT = 20
PHASES = ("synthesize", "wav_combine", "mp3_encode")
FAILURE_REASONS = (
    "script_missing",
    "tts_no_lines_succeeded",
    "tts_synthesis_exception",
    "wav_combine_failed",
    "mp3_encode_failed",
    "build_exception",
)
IN_PROGRESS_STATUSES = ("pending", "generating", "synthesizing", "awaiting_review")
LLM_ANOMALY_STATUSES = ("retry", "json_parse_failed")


def _utc_iso(value: str | None) -> str | None:
    """SQLite の UTC 日時を ISO 8601 形式へ正規化する。"""
    if value is None:
        return None
    normalized = value.replace(" ", "T")
    if normalized.endswith("Z") or "+" in normalized[10:]:
        return normalized
    return f"{normalized}+00:00"


@router.get("/admin/dashboard/stats", summary="運用ダッシュボードの集計値を取得")
def get_dashboard_stats(
    _: Annotated[int, Depends(require_owner_session)],
    range: Literal["7d", "30d"] = Query("7d"),
) -> dict:
    """直近 range の生成健全性指標を1回で返す（読み取り専用）。"""
    now = datetime.now(timezone.utc)
    # 秒精度の created_at 列と揃えるため、返却する since も秒に丸める。
    since = (now - timedelta(days=RANGE_DAYS[range])).replace(microsecond=0)
    since_text = since.strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        # 成功率: created_at 基準。discarded は集計に含めない。
        status_counts = {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM episodes WHERE created_at >= ? GROUP BY status",
                (since_text,),
            )
        }
        completed = status_counts.get("completed", 0)
        failed = status_counts.get("failed", 0)
        finished = completed + failed

        # phase logs の started_at は小数秒・オフセット付き ISO 8601。strftime(%f) でミリ秒精度の UTC 文字列へ正規化して比較する。
        duration_rows = {
            row["phase"]: row
            for row in conn.execute(
                "SELECT phase, AVG(duration_ms) AS avg_ms, MAX(duration_ms) AS max_ms, COUNT(*) AS n "
                "FROM episode_generation_phase_logs "
                "WHERE strftime('%Y-%m-%d %H:%M:%f', started_at) >= ? AND duration_ms IS NOT NULL GROUP BY phase",
                (since_text,),
            )
        }
        reason_counts = {
            row["failure_reason"]: row["n"]
            for row in conn.execute(
                "SELECT failure_reason, COUNT(*) AS n FROM episode_generation_phase_logs "
                "WHERE strftime('%Y-%m-%d %H:%M:%f', started_at) >= ? AND failure_reason IS NOT NULL GROUP BY failure_reason",
                (since_text,),
            )
        }
        recent_failures = conn.execute(
            "SELECT started_at, episode_id, phase, failure_reason FROM episode_generation_phase_logs "
            "WHERE strftime('%Y-%m-%d %H:%M:%f', started_at) >= ? AND failure_reason IS NOT NULL "
            # 同一ミリ秒内は保存値(マイクロ秒、同一オフセットで辞書順=時刻順)で並べる。
            "ORDER BY strftime('%Y-%m-%d %H:%M:%f', started_at) DESC, started_at DESC, id DESC LIMIT ?",
            (since_text, RECENT_FAILURE_LIMIT),
        ).fetchall()

        llm_rows = conn.execute(
            "SELECT phase, status, COUNT(*) AS n, AVG(latency_ms) AS avg_ms, MAX(latency_ms) AS max_ms "
            "FROM llm_call_logs WHERE created_at >= ? GROUP BY phase, status",
            (since_text,),
        ).fetchall()
        llm_latency_rows = conn.execute(
            "SELECT phase, COUNT(*) AS n, AVG(latency_ms) AS avg_ms, MAX(latency_ms) AS max_ms "
            "FROM llm_call_logs WHERE created_at >= ? GROUP BY phase ORDER BY phase",
            (since_text,),
        ).fetchall()

        pending_reports = conn.execute(
            "SELECT COUNT(*) AS n FROM misreading_reports WHERE approved = 0"
        ).fetchone()["n"]
        awaiting_review = conn.execute(
            "SELECT COUNT(*) AS n FROM episodes WHERE status = 'awaiting_review'"
        ).fetchone()["n"]

    llm_anomalies_by_phase: dict[str, dict[str, int]] = {}
    llm_anomaly_totals = {status: 0 for status in LLM_ANOMALY_STATUSES}
    llm_error_count = 0
    for row in llm_rows:
        if row["status"] == "error":
            llm_error_count += row["n"]
        elif row["status"] in LLM_ANOMALY_STATUSES:
            llm_anomaly_totals[row["status"]] += row["n"]
            phase_entry = llm_anomalies_by_phase.setdefault(
                row["phase"], {status: 0 for status in LLM_ANOMALY_STATUSES}
            )
            phase_entry[row["status"]] += row["n"]

    def _round(value: float | None) -> float | None:
        return None if value is None else round(value, 1)

    return {
        "range": range,
        "since": since.isoformat(),
        "generated_at": now.isoformat(),
        "episodes": {
            "completed": completed,
            "failed": failed,
            "in_progress": sum(status_counts.get(s, 0) for s in IN_PROGRESS_STATUSES),
            "success_rate": (completed / finished) if finished else None,
        },
        "phase_durations": [
            {
                "phase": phase,
                "count": duration_rows[phase]["n"] if phase in duration_rows else 0,
                "avg_ms": _round(duration_rows[phase]["avg_ms"]) if phase in duration_rows else None,
                "max_ms": duration_rows[phase]["max_ms"] if phase in duration_rows else None,
            }
            for phase in PHASES
        ],
        "failures": {
            "by_reason": {reason: reason_counts.get(reason, 0) for reason in FAILURE_REASONS},
            "llm_error_count": llm_error_count,
            "recent": [
                {
                    "occurred_at": _utc_iso(row["started_at"]),
                    "episode_id": row["episode_id"],
                    "phase": row["phase"],
                    "reason": row["failure_reason"],
                }
                for row in recent_failures
            ],
        },
        "llm": {
            "latency_by_phase": [
                {
                    "phase": row["phase"],
                    "call_count": row["n"],
                    "avg_latency_ms": _round(row["avg_ms"]),
                    "max_latency_ms": row["max_ms"],
                }
                for row in llm_latency_rows
            ],
            "retry_count": llm_anomaly_totals["retry"],
            "json_parse_failed_count": llm_anomaly_totals["json_parse_failed"],
            "anomalies_by_phase": [
                {
                    "phase": phase,
                    "retry_count": counts["retry"],
                    "json_parse_failed_count": counts["json_parse_failed"],
                }
                for phase, counts in sorted(llm_anomalies_by_phase.items())
            ],
        },
        "pending": {
            "unapproved_misreading_reports": pending_reports,
            "awaiting_review_episodes": awaiting_review,
        },
    }
