"""Telegram generation notifications.

通知は生成処理の結果を変更しない best-effort の副作用として扱う。
Bot token は設定からのみ読み込み、本文・ログ・例外へ含めない。
"""

import logging
import re
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_MAX_ERROR_LENGTH = 240
_SECRET_PATTERNS = (
    re.compile(r"(?i)(?:bot)?\d{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
)


def sanitize_error(error: Any) -> str:
    """Return a short operator-safe error summary."""
    value = " ".join(str(error).split())
    configured_token = get_settings().telegram_bot_token
    if configured_token:
        value = value.replace(configured_token, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value[:_MAX_ERROR_LENGTH] or "不明なエラー"


def _send_message(text: str) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram notification skipped: sender is not configured")
        return False

    endpoint = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        response = httpx.post(
            endpoint,
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except Exception:
        # token/chat id and response body are intentionally not logged.
        logger.warning("Telegram notification failed")
        return False


def notify_success(*, title: str, episode_id: int, seq: int, public_url: str | None = None) -> bool:
    """Send one successful-generation notification."""
    settings = get_settings()
    url = public_url or f"{settings.public_base_url.rstrip('/')}/episodes/{episode_id}"
    text = f"✅ Mynews-Radio 番組生成完了\nタイトル: {title}\nエピソード番号: {seq}\n公開URL: {url}"
    return _send_message(text)


def notify_failure(*, episode_id: int, phase: str, error: Any) -> bool:
    """Send one failed-generation notification with a sanitized error summary."""
    text = (
        "❌ Mynews-Radio 番組生成失敗\n"
        f"エピソード番号: {episode_id}\n"
        f"失敗工程: {sanitize_error(phase)}\n"
        f"エラー概要: {sanitize_error(error)}"
    )
    return _send_message(text)
