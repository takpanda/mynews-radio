"""Reset stale episodes stuck in generating status to pending."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService


def reset_stale_generating() -> int:
    """Reset all generating episodes for safe reuse and return the count."""
    service = EpisodeService()

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM episodes WHERE status = 'generating'"
        ).fetchall()

    for row in rows:
        service.reset_episode_for_reuse(row["id"])

    return len(rows)


def main() -> None:
    try:
        count = reset_stale_generating()
    except Exception as exc:
        print(f"Error connecting to database: {exc}")
        raise SystemExit(1)

    if count == 0:
        print("No generating episodes found. Nothing to update.")
    else:
        print(f"Updated {count} episode(s) from generating to pending.")


if __name__ == "__main__":
    main()
