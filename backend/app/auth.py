"""管理者ログイン、セッション、管理API認証。"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Header, HTTPException

from app.config import get_settings
from app.db.connection import get_db_connection

PBKDF2_ITERATIONS = 310_000
SALT_LENGTH = 16
TOKEN_LENGTH = 32
SESSION_DURATION_HOURS = 24
SESSION_COOKIE_NAME = "admin_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(SALT_LENGTH)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, stored = password_hash.split("$", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
        )
        return hmac.compare_digest(digest.hex(), stored)
    except (ValueError, AttributeError):
        return False


def generate_session_token() -> str:
    return secrets.token_hex(TOKEN_LENGTH)


def create_session(admin_user_id: int) -> str:
    token = generate_session_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (admin_user_id, token, expires_at) VALUES (?, ?, ?)",
            (admin_user_id, token, expires_at),
        )
    return token


def delete_session(token: str) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_admin_user_id_by_session(token: str) -> Optional[int]:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT admin_user_id, expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    if row is None:
        return None
    expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    if expires_at < datetime.now(timezone.utc):
        delete_session(token)
        return None
    return row["admin_user_id"]


def _resolve_token(
    authorization: Optional[str] = Header(None),
    admin_session: Optional[str] = Cookie(None),
) -> tuple[str, str]:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        source = "bearer"
    elif admin_session:
        token = admin_session
        source = "session"
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token, source


def require_admin(
    authorization: Optional[str] = Header(None),
    admin_session: Optional[str] = Cookie(None),
) -> int:
    token, source = _resolve_token(authorization, admin_session)
    if source == "bearer":
        settings = get_settings()
        if not settings.api_key or not hmac.compare_digest(token, settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        # API_KEYは後方互換のサービス資格情報として維持する。
        return -1
    user_id = get_admin_user_id_by_session(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_id


def require_admin_with_token(
    authorization: Optional[str] = Header(None),
    admin_session: Optional[str] = Cookie(None),
) -> tuple[int, str]:
    token, source = _resolve_token(authorization, admin_session)
    if source == "bearer":
        settings = get_settings()
        if not settings.api_key or not hmac.compare_digest(token, settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return -1, token
    user_id = get_admin_user_id_by_session(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_id, token
