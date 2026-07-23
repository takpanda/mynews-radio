import getpass
import sys

from app.auth import hash_password
from app.db.connection import get_db_connection


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/create_admin.py <username>")
    username = sys.argv[1]
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password again: "):
        raise SystemExit("passwords do not match")
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )


if __name__ == "__main__":
    main()
