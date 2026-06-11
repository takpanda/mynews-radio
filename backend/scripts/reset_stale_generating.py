"""Reset stale episodes stuck in generating status to pending."""

import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)


def reset_stale_generating() -> int:
    """Select all episodes with status='generating', update each to 'pending'.

    Returns the number of episodes that were reset.
    """
    service = EpisodeService()

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM episodes WHERE status = 'generating'"
        ).fetchall()

    count = 0
    for row in rows:
        episode_id = row["id"]
        service.update_episode_status(episode_id, "pending")
        logger.info("Reset episode %d from generating to pending", episode_id)
        count += 1

    if count == 0:
        logger.info("No stale generating episodes found.")
    else:
        logger.info("Reset %d stale generating episode(s).", count)

    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    reset_stale_generating()
