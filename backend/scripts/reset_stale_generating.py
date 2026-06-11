import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import get_db_connection


def main():
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id FROM episodes
            WHERE status = ?
            """,
            ("generating",),
        ).fetchall()

        count = len(rows)

        if count == 0:
            print("No generating episodes found. Nothing to update.")
            return

        conn.execute(
            """
            UPDATE episodes
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE status = ?
            """,
            ("pending", "generating"),
        )

        print(f"Updated {count} episode(s) from generating to pending.")


if __name__ == "__main__":
    main()
