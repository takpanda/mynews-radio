"""検証済みクライアントIPのリレー署名を検証する。"""

import hashlib
import hmac
import ipaddress
import time

from fastapi import Request

from app.config import get_settings

HEADER_IP = "X-Verified-Client-IP"
HEADER_TIMESTAMP = "X-Verified-Client-IP-Timestamp"
HEADER_SIGNATURE = "X-Verified-Client-IP-Signature"
MAX_AGE_SECONDS = 60


def signing_payload(client_ip: str, method: str, path: str, timestamp: str) -> str:
    return "\n".join((client_ip, method.upper(), path, timestamp))


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    # 署名は受信した生値に対して行うため、表記の正規化は採用時に行わない。
    return value if str(parsed) == value else None


def get_verified_client_ip(request: Request) -> str:
    """署名が有効なIPだけを返し、それ以外はTCP接続元へ戻す。"""
    fallback = request.client.host if request.client else "unknown"
    client_ip = _valid_ip(request.headers.get(HEADER_IP))
    timestamp = request.headers.get(HEADER_TIMESTAMP)
    signature = request.headers.get(HEADER_SIGNATURE)
    secret = get_settings().proxy_client_ip_hmac_secret
    if not client_ip or not timestamp or not signature or not secret:
        return fallback
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return fallback
    if abs(int(time.time()) - timestamp_value) > MAX_AGE_SECONDS:
        return fallback

    expected = hmac.new(
        secret.encode("utf-8"),
        signing_payload(client_ip, request.method, request.url.path, timestamp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return fallback
    return client_ip
