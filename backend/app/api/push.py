"""Web Push購読の登録・解除とVAPID公開鍵API。"""

import base64
import hashlib
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from app.config import get_settings
from app.api.generate import limiter
from app.db.connection import get_db_connection

router = APIRouter(prefix="/push", tags=["push"])


def _rate_limit() -> str:
    return get_settings().push_rate_limit


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=16, max_length=256)
    auth: str = Field(min_length=8, max_length=128)

    @field_validator("p256dh", "auth")
    @classmethod
    def validate_base64url(cls, value: str) -> str:
        try:
            base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except Exception as exc:
            raise ValueError("key must be base64url encoded") from exc
        return value


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute HTTP(S) URL")
        return value


class PushSubscriptionResponse(BaseModel):
    subscription_id: str


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_subscription_id() -> tuple[str, str]:
    value = secrets.token_urlsafe(32)
    return value, _hash(value)


@router.get("/vapid-public-key")
def get_vapid_public_key() -> dict[str, str]:
    key = get_settings().vapid_public_key
    if not key:
        raise HTTPException(status_code=503, detail="Web Push is not configured")
    return {"public_key": key}


@router.post("/subscriptions", response_model=PushSubscriptionResponse)
@limiter.limit(_rate_limit)
def register_subscription(request: Request, body: PushSubscriptionRequest) -> PushSubscriptionResponse:
    """購読先自体は返さず、解除専用の短期利用識別子だけを返す。"""
    endpoint_hash = _hash(body.endpoint)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT subscription_id_hash FROM push_subscriptions WHERE endpoint_hash = ?",
            (endpoint_hash,),
        ).fetchone()
        subscription_id, subscription_id_hash = _new_subscription_id()
        if row:
            # 再購読時は鍵を最新化し、旧識別子を無効化する。
            conn.execute(
                "UPDATE push_subscriptions SET subscription_id_hash = ?, p256dh = ?, auth = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE endpoint_hash = ?",
                (subscription_id_hash, body.keys.p256dh, body.keys.auth, endpoint_hash),
            )
        else:
            conn.execute(
                "INSERT INTO push_subscriptions (subscription_id_hash, endpoint_hash, endpoint, p256dh, auth) VALUES (?, ?, ?, ?, ?)",
                (subscription_id_hash, endpoint_hash, body.endpoint, body.keys.p256dh, body.keys.auth),
            )
    return PushSubscriptionResponse(subscription_id=subscription_id)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
@limiter.limit(_rate_limit)
def unregister_subscription(request: Request, subscription_id: str) -> None:
    """解除は登録時に発行した不透明な識別子で行う（未登録でも冪等に204）。"""
    if not subscription_id or len(subscription_id) > 128:
        return
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE push_subscriptions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE subscription_id_hash = ?",
            (_hash(subscription_id),),
        )
