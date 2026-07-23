from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    require_admin_with_token,
    verify_password,
)
from app.config import get_settings
from app.db.connection import get_db_connection

router = APIRouter(tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/admin/login")
def admin_login(body: LoginRequest, response: Response) -> dict:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM admin_users WHERE username = ?",
            (body.username,),
        ).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session(row["id"])
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=24 * 60 * 60,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"admin_user_id": row["id"], "username": row["username"]}


@router.post("/admin/logout")
def admin_logout(
    response: Response,
    admin_context: Annotated[tuple[int, str], Depends(require_admin_with_token)],
) -> dict:
    _, token = admin_context
    if token:
        delete_session(token)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/admin/me")
def admin_me(
    admin_user_id: Annotated[tuple[int, str], Depends(require_admin_with_token)],
) -> dict:
    user_id, _ = admin_user_id
    if user_id < 0:
        raise HTTPException(status_code=401, detail="Admin user not found")
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, username FROM admin_users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Admin user not found")
    return {"admin_user_id": row["id"], "username": row["username"]}
