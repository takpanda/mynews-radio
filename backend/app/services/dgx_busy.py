"""Best-effort shared busy gate for the .102 generation services."""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")
_DOWN_ATTEMPTS = 3
_DOWN_RETRY_DELAY = 1.0


def _post_busy(endpoint: str, timeout: float, token: str | None = None):
    settings = get_settings()
    params = {"token": token} if token else None
    if endpoint == "up":
        params = {"lease": "true"}  # opt in to confirm/token claims
    response = httpx.post(
        f"{settings.thumbnail_service_url.rstrip('/')}/busy/{endpoint}",
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def _acquire_busy(stage: str) -> tuple[bool, str | None]:
    """Acquire the gate; returns (acquired, token).

    The server holds a claim as pending until /busy/confirm, and reclaims it if
    the confirmation never arrives, so a lost /busy/up response cannot leak the
    gate. Servers that return no token (older versions) skip the confirmation.
    """
    token = None
    try:
        settings = get_settings()
        # /busy/up waits until the shared gate is available, which can exceed
        # the normal per-request timeout while a thumbnail renders. Bound it
        # so a stuck gate never hangs the batch.
        response = _post_busy("up", settings.dgx_busy_wait_timeout)
        try:
            token = response.json().get("token")
        except Exception:
            token = None
        if token:
            _post_busy("confirm", settings.thumbnail_http_timeout, token)
        return True, token
    except Exception:
        logger.warning(".102 busy/up request failed (stage=%s)", stage)
        if token:
            # Claim may exist server-side; release it by token (idempotent).
            _release_busy(stage, token)
        return False, None


def _release_busy(stage: str, token: str | None) -> bool:
    # A token-scoped down is idempotent, so retry it: a lost response must not
    # leave the gate held. Token-less (legacy server) is tried once as before.
    attempts = _DOWN_ATTEMPTS if token else 1
    for attempt in range(attempts):
        try:
            _post_busy("down", get_settings().thumbnail_http_timeout, token)
            return True
        except Exception:
            logger.warning(
                ".102 busy/down request failed (stage=%s, attempt=%d/%d)",
                stage, attempt + 1, attempts,
            )
            if attempt + 1 < attempts:
                time.sleep(_DOWN_RETRY_DELAY * (attempt + 1))
    return False


def run_with_dgx_busy(stage: str, operation: Callable[..., T], *args, **kwargs) -> T:
    """Run one LLM/TTS phase, holding .102's shared busy gate when available.

    If the gate cannot be acquired (timeout / service down) the phase continues
    without it, and /busy/down is NOT called so another holder's counter is
    left untouched.
    """
    acquired, token = _acquire_busy(stage)
    if not acquired:
        logger.warning(
            ".102 busy gate unavailable; continuing without it (stage=%s)", stage
        )
        return operation(*args, **kwargs)
    try:
        return operation(*args, **kwargs)
    finally:
        _release_busy(stage, token)
