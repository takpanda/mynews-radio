"""
Batch job to remove episodes older than EPISODE_RETENTION_DAYS.

Deletes matching DB records (episodes + episode_items) and all associated
files in the episode directory (WAV, MP3, JSON artifacts).
"""

import json
import logging
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)

EPISODES_DIR = os.getenv("EPISODES_DIR", os.path.join("data", "episodes"))


def _delete_episode_directory(episode_date: str) -> int:
    """エピソードディレクトリ配下の全ファイルを削除し、削除数を返す"""
    episode_dir = os.path.join(EPISODES_DIR, episode_date)
    deleted_count = 0

    if not os.path.isdir(episode_dir):
        return deleted_count

    # Collect all files first (avoid modification during walk)
    for root, dirs, files in os.walk(episode_dir, topdown=False):
        for f in files:
            filepath = os.path.join(root, f)
            try:
                os.remove(filepath)
                deleted_count += 1
            except OSError as e:
                logger.warning("Failed to delete file %s: %s", filepath, e)

        # Remove subdirectories (bottom-up after files are gone)
        for d in reversed(dirs):
            dirpath = os.path.join(root, d)
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError as e:
                logger.warning("Failed to remove directory %s: %s", dirpath, e)

    # Remove the top-level episode_dir if it still exists
    if os.path.isdir(episode_dir):
        try:
            shutil.rmtree(episode_dir)
            logger.debug("Removed episode directory: %s", episode_dir)
        except OSError as e:
            logger.warning("Failed to remove episode directory %s: %s", episode_dir, e)

    return deleted_count


def cleanup_episodes() -> dict:
    """保持期間を超過したエピソードを一括削除する"""
    settings = get_settings()
    retention_days = settings.episode_retention_days

    logger.info("Starting episode cleanup. Retention=%d days", retention_days)

    ep_service = EpisodeService()

    # Step 1: Get expired episodes from DB
    expired = ep_service.get_expired_episodes(retention_days)
    if not expired:
        logger.info("No expired episodes found.")
        return {"deleted_count": 0, "files_deleted": 0}

    total_files_deleted = 0
    deleted_ids = []

    for ep in expired:
        episode_id = ep["id"]
        episode_date = ep["episode_date"]

        logger.info("Cleanup target: id=%d, date=%s", episode_id, episode_date)

        # Delete both possible directories (date-based legacy and id-based current)
        files_count = 0
        files_count += _delete_episode_directory(str(episode_id))
        files_count += _delete_episode_directory(episode_date)
        total_files_deleted += files_count

        # Then delete DB records
        cleaned = ep_service.delete_episode(episode_id)
        if cleaned:
            deleted_ids.append(episode_id)
            logger.info("Deleted DB record for episode id=%d, date=%s (deleted %d files)",
                        episode_id, episode_date, files_count)

    result = {
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "files_deleted": total_files_deleted,
    }

    logger.info("Episode cleanup completed: %s", json.dumps(result))
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    result = cleanup_episodes()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
