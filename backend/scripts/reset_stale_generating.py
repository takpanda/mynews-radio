import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import get_db_connection


def main():
    count = 0
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE status = ?
                """,
                ("pending", "generating"),
            )
            count = conn.total_changes

    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise SystemExit(1)

    if count == 0:
        print("No generating episodes found. Nothing to update.")
    else:
        print(f"Updated {count} episode(s) from generating to pending.")


if __name__ == "__main__":
    main()
