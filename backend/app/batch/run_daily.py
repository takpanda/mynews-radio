#!/usr/bin/env python3
""" daily batch orchestration script

Delegates to the shared radio pipeline.
"""
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.radio_pipeline import PipelineResult, run_radio_pipeline  # noqa: E402
from app.batch.cleanup_episodes import cleanup_episodes  # noqa: E402
from app.config import get_settings                       # noqa: E402
from app.logging_config import setup_daily_logging       # noqa: E402
from app.services.episode_service import EpisodeService   # noqa: E402
from app.db.connection import get_db_connection         # noqa: E402
from app.db.migration import ensure_generation_system_owner  # noqa: E402
from app.services.generation_control import (            # noqa: E402
    JobClaim,
    enqueue_job,
    finish_job,
)
from app.programs.serialization import program_profile_to_definition  # noqa: E402

logger = logging.getLogger(__name__)

_TTS_ENGINES = {"voicevox", "aivispeech", "fishs2pro"}


def main() -> None:
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== daily batch start (run_daily.py) ===")

    news_source = os.environ.get("BATCH_NEWS_SOURCE", "hatena_bookmark")
    episode_date = os.environ.get("BATCH_DATE") or dt.date.today().isoformat()
    program_id = os.environ.get("BATCH_PROGRAM_ID")
    program_profile = None
    program_snapshot = None
    if program_id is not None:
        # APIと同じ検証を使い、未登録・無効な番組やDB障害を
        # enqueue前に失敗させる。明示指定を既定番組へフォールバックしない。
        from app.api.generate import GenerateRequest, _resolve_program_profile

        program_profile = _resolve_program_profile(
            GenerateRequest(date=episode_date, program_id=program_id, news_source=news_source)
        )
        program_snapshot = json.dumps(
            program_profile_to_definition(program_profile), ensure_ascii=False
        )

    # 定期ニュース生成はエンジン未指定時、API/UIとは別に batch_default_tts_engine
    # (既定 fishs2pro) を使う。POST /generate 等の未指定時は従来どおり
    # settings.default_tts_engine (aivispeech) を維持するため、経路をここで分離する。
    settings = get_settings()
    batch_tts_engine = (
        settings.batch_default_tts_engine
        if settings.batch_default_tts_engine in _TTS_ENGINES
        else settings.default_tts_engine
    )

    with get_db_connection() as conn:
        owner_id = ensure_generation_system_owner(conn)
    payload = {"date": episode_date, "news_source": news_source, "tts_engine": batch_tts_engine}
    if program_id is not None:
        payload["program_id"] = program_id
    claim = enqueue_job(
        owner_id, "daily", f"daily-{episode_date}",
        payload,
        # cronプロセスはenqueue後に終了するため、daemon dispatcherへ任せると
        # activeジョブを実行する前にワーカーごと消える。active claimはこの
        # プロセス内で同期実行し、waitingの場合だけ永続キューに残す。
        episode_date=episode_date, client_ip="cron", dispatch=False,
        program_id=program_profile.id if program_profile is not None else None,
        program_snapshot=program_snapshot,
    )
    logger.info("Daily generation queued: job_id=%d status=%s", claim.job_id, claim.status)
    if claim.duplicate or claim.status != "active":
        return

    current_job_id: int | None = claim.job_id
    current_episode_id: int | None = claim.episode_id
    while current_job_id is not None:
        try:
            promoted = _execute_claimed_job(current_job_id)
        except Exception:
            # どの段階のジョブでも、例外対象を終端化してからFIFOを継続する。
            logger.exception("daily generation execution failed: job_id=%d", current_job_id)
            if current_episode_id is not None:
                try:
                    EpisodeService().update_episode_status(current_episode_id, "failed")
                except Exception:
                    logger.exception("failed to mark daily episode as failed: episode_id=%d", current_episode_id)
            try:
                promoted = finish_job(current_job_id, False, dispatch=False)
            except Exception:
                logger.exception("failed to finish daily generation job: job_id=%d", current_job_id)
                promoted = None
        current_job_id = promoted.job_id if promoted else None
        current_episode_id = promoted.episode_id if promoted else None


def _execute_claimed_job(job_id: int) -> JobClaim | None:
    """コミット済みジョブを読み込み、cronプロセス終了前に実行する。"""
    with get_db_connection() as conn:
        job = conn.execute(
            "SELECT * FROM generation_jobs WHERE id = ? AND status = 'active'", (job_id,)
        ).fetchone()
    if job is None:
        logger.warning("daily generation claim is no longer active: job_id=%d", job_id)
        return

    # API起点と同じ監査・finish_job・次ジョブ昇格の経路を利用する。
    from app.api.generate import execute_queued_job
    return execute_queued_job(job, dispatch=False)


def run_daily_job(job) -> bool:
    """ディスパッチャから実行されるcron本体。"""
    payload = json.loads(job["payload"] or "{}")
    episode_id = job["episode_id"]
    episode = EpisodeService().get_episode(episode_id)
    if episode is None:
        _write_manifest(status="failed")
        return False
    cleanup_result = cleanup_episodes()
    logger.info("=== daily retention cleanup complete: %s ===", cleanup_result)
    program_profile = None
    if payload.get("program_id") is not None:
        from app.api.generate import RADIO_PROGRAM_NEWS_SOURCES, _episode_program_profile

        program_profile = _episode_program_profile(episode_id)
        if program_profile is None or program_profile.id != payload["program_id"]:
            raise RuntimeError("指定番組のsnapshotをepisodeから取得できません")
        news_source = RADIO_PROGRAM_NEWS_SOURCES.get(program_profile.id, "hatena_hotentry_all")
    else:
        news_source = payload.get("news_source", "hatena_bookmark")
    metadata = run_radio_pipeline(
        episode_id,
        episode_date=payload["date"],
        news_source=news_source,
        seq=episode.get("seq", 0),
        tts_engine=payload.get("tts_engine"),
        default_episodes_dir="data/episodes",
        program_profile=program_profile,
    )
    if metadata is PipelineResult.NO_CONTENT:
        logger.info("=== daily batch complete - no new articles ===")
        _write_manifest(status="done")
        return True
    if metadata is PipelineResult.REVIEW_REQUIRED:
        logger.info("=== daily batch complete - awaiting script review (episode %d) ===", episode_id)
        _write_manifest(status="awaiting_review")
        return True
    if metadata is not None:
        logger.info("=== daily batch complete - %s ===", metadata.get("title", f"episode {episode_id}"))
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        _write_manifest(status="done", metadata=metadata)
        return True
    _write_manifest(status="failed")
    return False


def _write_manifest(status: str = "", metadata: dict | None = None) -> None:
    """Persist last-run info as /app/data/run_manifest.json."""
    manifest_path = "/app/data/run_manifest.json"
    payload = {"status": status}
    if metadata:
        payload["metadata"] = metadata
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
