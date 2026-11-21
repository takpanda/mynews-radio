#!/usr/bin/env python3
"""週末ダイジェスト回の週次バッチ（毎週日曜 8:00 JST にcronから起動）。

通常回と同じ生成ジョブキューに登録するため、通常回やAPI起点の生成と
DGX/TTSを同時に使わない（先行ジョブがあれば待機し、完了後に実行される）。

手動実行: python3 -m app.batch.run_weekly_digest  （BATCH_DATE=YYYY-MM-DD で対象日を指定可）
"""
import datetime as dt
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.run_daily import resolve_batch_tts_engine, run_claimed_jobs  # noqa: E402
from app.batch.weekly_digest import (  # noqa: E402
    DIGEST_EPISODE_TYPE,
    WEEKLY_DIGEST_OPERATION,
    digest_idempotency_key,
    digest_today,
    find_week_digest,
    iso_week_label,
)
from app.db.connection import get_db_connection  # noqa: E402
from app.db.migration import ensure_generation_system_owner  # noqa: E402
from app.logging_config import setup_daily_logging  # noqa: E402
from app.services.generation_control import GenerationControlError, enqueue_job  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== weekly digest batch start (run_weekly_digest.py) ===")

    target = dt.date.fromisoformat(os.environ["BATCH_DATE"]) if os.environ.get("BATCH_DATE") else digest_today()
    week = iso_week_label(target)

    # 同一ISO週に失敗していないダイジェストがあれば生成しない（二重生成防止）。
    existing = find_week_digest(target)
    if existing is not None:
        logger.info(
            "Weekly digest already exists for %s: episode_id=%d status=%s; skipping",
            week, existing["id"], existing["status"],
        )
        return

    with get_db_connection() as conn:
        owner_id = ensure_generation_system_owner(conn)
    # 対象記事の完成時刻の上限。キュー待機中に完成した通常回を含めないよう起動時刻で固定する。
    started_at = dt.datetime.now(dt.timezone.utc)
    payload = {
        "date": target.isoformat(),
        "iso_week": week,
        "cutoff": started_at.isoformat(),
        "tts_engine": resolve_batch_tts_engine(),
    }
    try:
        claim = enqueue_job(
            owner_id, WEEKLY_DIGEST_OPERATION, digest_idempotency_key(target), payload,
            episode_date=target.isoformat(), episode_type=DIGEST_EPISODE_TYPE,
            # cronプロセスはenqueue後に終了するため、active claimはこのプロセス内で
            # 同期実行し、waitingの場合だけ永続キューに残す（run_daily.py と同じ方針）。
            client_ip="cron", dispatch=False,
        )
    except GenerationControlError as exc:
        # 同時起動した別プロセスが同じ試行キーで先にキューへ登録済み(起動時刻が違うため入力不一致になる)。
        if exc.status_code == 409:
            logger.info("Weekly digest for %s is already queued by another process; skipping", week)
            return
        raise
    logger.info("Weekly digest queued: job_id=%d status=%s", claim.job_id, claim.status)
    if claim.duplicate or claim.status != "active":
        return
    run_claimed_jobs(claim)


if __name__ == "__main__":
    main()
