#!/usr/bin/env python3
""" daily batch orchestration script

Delegates to the shared radio pipeline.
"""
import datetime as dt
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.radio_pipeline import PipelineResult, run_radio_pipeline  # noqa: E402
from app.batch.cleanup_episodes import cleanup_episodes  # noqa: E402
from app.config import get_settings                       # noqa: E402
from app.logging_config import setup_daily_logging       # noqa: E402
from app.services.episode_service import EpisodeService   # noqa: E402
from app.db.connection import get_db_connection         # noqa: E402
from app.services.generation_control import (            # noqa: E402
    SYSTEM_OWNER_USERNAME, enqueue_job,
)

logger = logging.getLogger(__name__)

_TTS_ENGINES = {"voicevox", "aivispeech", "fishs2pro"}


def main() -> None:
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== daily batch start (run_daily.py) ===")

    news_source = os.environ.get("BATCH_NEWS_SOURCE", "hatena_bookmark")
    episode_date = os.environ.get("BATCH_DATE") or dt.date.today().isoformat()

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
        conn.execute(
            "INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES (?, ?)",
            (SYSTEM_OWNER_USERNAME, "disabled$generation_queue"),
        )
        owner_id = conn.execute(
            "SELECT id FROM admin_users WHERE username = ?", (SYSTEM_OWNER_USERNAME,)
        ).fetchone()[0]
    claim = enqueue_job(
        owner_id, "daily", f"daily-{episode_date}",
        {"date": episode_date, "news_source": news_source, "tts_engine": batch_tts_engine},
        episode_date=episode_date, client_ip="cron", dispatch=True,
    )
    logger.info("Daily generation queued: job_id=%d status=%s", claim.job_id, claim.status)
    if claim.status != "active":
        return
    while True:
        with get_db_connection() as conn:
            row = conn.execute("SELECT status FROM generation_jobs WHERE id = ?", (claim.job_id,)).fetchone()
        if not row or row["status"] != "active":
            break
        time.sleep(0.1)
    if row and row["status"] == "failed":
        sys.exit(1)


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
    metadata = run_radio_pipeline(
        episode_id,
        episode_date=payload["date"],
        news_source=payload.get("news_source", "hatena_bookmark"),
        seq=episode.get("seq", 0),
        tts_engine=payload.get("tts_engine"),
        default_episodes_dir="data/episodes",
    )
    if metadata is PipelineResult.NO_CONTENT:
        logger.info("=== daily batch complete - no new articles ===")
        _write_manifest(status="done")
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
