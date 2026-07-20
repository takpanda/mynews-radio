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

from app.batch.radio_pipeline import run_radio_pipeline  # noqa: E402
from app.logging_config import setup_daily_logging       # noqa: E402
from app.services.episode_service import EpisodeService   # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== daily batch start (run_daily.py) ===")

    news_source = os.environ.get("BATCH_NEWS_SOURCE", "hatena_bookmark")
    episode_date = os.environ.get("BATCH_DATE") or dt.date.today().isoformat()

    episode_service = EpisodeService()
    episode_id, seq = episode_service.create_radio_episode(
        episode_date=episode_date, status="generating",
    )
    logger.info("Episode record created: id=%d, date=%s, seq=%d", episode_id, episode_date, seq)

    metadata = run_radio_pipeline(
        episode_id,
        episode_date=episode_date,
        news_source=news_source,
        seq=seq,
        default_episodes_dir="data/episodes",
    )

    if metadata is not None:
        logger.info(
            "=== daily batch complete - %s ===",
            metadata.get("title", f"episode {episode_id}"),
        )
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        _write_manifest(status="done", metadata=metadata)
    else:
        _write_manifest(status="failed")
        sys.exit(1)


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
