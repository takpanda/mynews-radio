"""音声合成・音声結合の行単位・工程別詳細ログ（BEE-718）。

既存の監査ログ（app/audit.py, audit_logs）とは責務が異なる。audit_logs は
「操作の受付〜完了」を1〜数レコードで記録する監査目的だが、このモジュールは
synthesize_voicevox.py / build_episode.py の内部処理（行ごとのTTS結果、WAV結合、
MP3変換）を後から調査できるように永続化する。

書き込みは呼び出し元の生成処理を止めないことを優先し、失敗時は例外を投げず
ログ記録のみを諦める（best-effort）。台本本文・生IPアドレス・認証情報・
冪等性キーは保存しない。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_phase_log(
    episode_id: int,
    phase: str,
    *,
    generation_job_id: Optional[int] = None,
    tts_engine: Optional[str] = None,
) -> Optional[int]:
    """工程attempt(実行)を開始し、phase_log_idを返す。

    同一episode_id×phase内の実行順(attempt_no)は自動採番する（再合成に対応）。
    書き込みに失敗してもNoneを返すだけで、生成処理自体は継続させる。
    """
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_attempt "
                "FROM episode_generation_phase_logs WHERE episode_id = ? AND phase = ?",
                (episode_id, phase),
            ).fetchone()
            attempt_no = row["next_attempt"]
            cursor = conn.execute(
                "INSERT INTO episode_generation_phase_logs "
                "(episode_id, generation_job_id, phase, attempt_no, tts_engine, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (episode_id, generation_job_id, phase, attempt_no, tts_engine, _now()),
            )
            return int(cursor.lastrowid)
    except Exception:
        logger.exception(
            "phase logの開始に失敗しました（記録のみ諦め処理は継続） episode_id=%s phase=%s",
            episode_id, phase,
        )
        return None


def finalize_phase_log(
    phase_log_id: Optional[int],
    *,
    result: str,
    line_success_count: Optional[int] = None,
    line_total_count: Optional[int] = None,
    failure_reason: Optional[str] = None,
) -> None:
    """開始済みのphase attemptを確定する。phase_log_idがNoneの場合は何もしない。"""
    if phase_log_id is None:
        return
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT started_at FROM episode_generation_phase_logs WHERE id = ?",
                (phase_log_id,),
            ).fetchone()
            if row is None:
                return
            ended_at = _now()
            duration_ms = None
            try:
                started = datetime.fromisoformat(row["started_at"])
                ended = datetime.fromisoformat(ended_at)
                duration_ms = int((ended - started).total_seconds() * 1000)
            except (TypeError, ValueError):
                pass
            conn.execute(
                "UPDATE episode_generation_phase_logs "
                "SET result = ?, ended_at = ?, duration_ms = ?, "
                "    line_success_count = ?, line_total_count = ?, failure_reason = ? "
                "WHERE id = ?",
                (result, ended_at, duration_ms, line_success_count, line_total_count,
                 failure_reason, phase_log_id),
            )
    except Exception:
        logger.exception("phase logの確定に失敗しました phase_log_id=%s", phase_log_id)


def record_line_log(
    phase_log_id: Optional[int],
    episode_id: int,
    script_line_index: int,
    *,
    generation_job_id: Optional[int] = None,
    speaker: Optional[str] = None,
    section: Optional[str] = None,
    delivery: Optional[str] = None,
    tts_engine: Optional[str] = None,
    synth_result: str,
    retry_count: int = 0,
    wav_file: Optional[str] = None,
    speaking_rate: Optional[float] = None,
    processing_duration_ms: Optional[int] = None,
    failure_reason: Optional[str] = None,
) -> None:
    """台本1行のTTS合成結果を記録する。phase_log_idがNoneの場合は何もしない。"""
    if phase_log_id is None:
        return
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO episode_generation_line_logs "
                "(phase_log_id, episode_id, generation_job_id, script_line_index, speaker, section, "
                " delivery, tts_engine, synth_result, retry_count, wav_file, speaking_rate, "
                " processing_duration_ms, failure_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (phase_log_id, episode_id, generation_job_id, script_line_index, speaker, section,
                 delivery, tts_engine, synth_result, retry_count, wav_file, speaking_rate,
                 processing_duration_ms, failure_reason),
            )
    except Exception:
        logger.exception(
            "line logの保存に失敗しました episode_id=%s script_line_index=%s",
            episode_id, script_line_index,
        )


def update_line_timing(
    episode_id: int,
    synthesize_phase_log_id: Optional[int],
    script_line_index: int,
    *,
    start_time_sec: Optional[float] = None,
    silence_before_sec: Optional[float] = None,
) -> bool:
    """build工程(wav_combine)で計算したstart_time/無音時間を該当行ログへ反映する。

    無音時間・開始時刻が実際の結合処理に使用した値と一致して保存されることは
    受入条件そのものであり、他のログ記録関数と異なり保存失敗を握りつぶさず
    呼び出し元(build_episode)へ bool で伝える。呼び出し元はFalseの場合、
    生成そのものを失敗として扱うこと。

    UPDATE文自体は対象行が0件でも例外にならないため、実行例外だけでなく
    `cursor.rowcount == 1` も確認する。record_line_log()のbest-effort書き込み
    失敗やattempt/行番号の不整合で対象の行ログが存在しない場合を、更新成功と
    誤判定しないようにするため。

    Returns:
        更新対象が無い(synthesize_phase_log_id が None)場合 True。
        更新が1行に一致した場合 True。
        DB更新例外、または一致した行が1件以外(0件・複数件)の場合 False。
    """
    if synthesize_phase_log_id is None:
        return True
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "UPDATE episode_generation_line_logs "
                "SET start_time_sec = ?, silence_before_sec = ? "
                "WHERE phase_log_id = ? AND script_line_index = ? AND episode_id = ?",
                (start_time_sec, silence_before_sec, synthesize_phase_log_id, script_line_index, episode_id),
            )
            if cursor.rowcount != 1:
                logger.error(
                    "line logのタイミング更新が対象行に一致しませんでした "
                    "(rowcount=%d) episode_id=%s phase_log_id=%s script_line_index=%s",
                    cursor.rowcount, episode_id, synthesize_phase_log_id, script_line_index,
                )
                return False
            return True
    except Exception:
        logger.exception(
            "line logのタイミング更新に失敗しました episode_id=%s script_line_index=%s",
            episode_id, script_line_index,
        )
        return False


def latest_phase_log_id(episode_id: int, phase: str) -> Optional[int]:
    """指定episodeの指定phaseで最も新しいattemptのphase_log_idを返す。"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM episode_generation_phase_logs "
                "WHERE episode_id = ? AND phase = ? ORDER BY attempt_no DESC LIMIT 1",
                (episode_id, phase),
            ).fetchone()
            return row["id"] if row else None
    except Exception:
        logger.exception(
            "直近phase_log_idの取得に失敗しました episode_id=%s phase=%s", episode_id, phase,
        )
        return None


def delete_generation_logs_for_episode(conn, episode_id: int) -> None:
    """エピソード削除に合わせて詳細ログを明示削除する。

    SQLite接続で PRAGMA foreign_keys が有効化されていないため、スキーマ上の
    ON DELETE CASCADE 宣言には依存せず、episode_service.delete_episode() と
    同一トランザクション内で明示 DELETE する。
    """
    conn.execute("DELETE FROM episode_generation_line_logs WHERE episode_id = ?", (episode_id,))
    conn.execute("DELETE FROM episode_generation_phase_logs WHERE episode_id = ?", (episode_id,))


def cleanup_generation_logs(now: Optional[datetime] = None) -> int:
    """保持期間(90日)を超えた詳細ログを削除する。基準はCOALESCE(ended_at, created_at)。

    削除したphase_log(attempt)件数を返す。
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = (reference - timedelta(days=RETENTION_DAYS)).isoformat()
    with get_db_connection() as conn:
        expired_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM episode_generation_phase_logs "
                "WHERE julianday(COALESCE(ended_at, created_at)) < julianday(?)",
                (cutoff,),
            ).fetchall()
        ]
        if not expired_ids:
            return 0
        placeholders = ",".join("?" for _ in expired_ids)
        conn.execute(
            f"DELETE FROM episode_generation_line_logs WHERE phase_log_id IN ({placeholders})",
            expired_ids,
        )
        conn.execute(
            f"DELETE FROM episode_generation_phase_logs WHERE id IN ({placeholders})",
            expired_ids,
        )
        return len(expired_ids)
