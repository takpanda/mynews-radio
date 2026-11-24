"""Best-effort shared busy gate for the .102 generation services."""

import logging
from collections.abc import Callable
from typing import TypeVar

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _set_busy(endpoint: str, stage: str) -> bool:
    try:
        settings = get_settings()
        response = httpx.post(
            f"{settings.thumbnail_service_url.rstrip('/')}/busy/{endpoint}",
            # /busy/up waits until the shared gate is available, which can exceed
            # the normal per-request timeout while a thumbnail renders. Bound it
            # so a stuck gate never hangs the batch.
            timeout=(
                settings.dgx_busy_wait_timeout
                if endpoint == "up"
                else settings.thumbnail_http_timeout
            ),
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(".102 busy/%s request failed (stage=%s)", endpoint, stage)
        return False


def run_with_dgx_busy(stage: str, operation: Callable[..., T], *args, **kwargs) -> T:
    """Run one LLM/TTS phase, holding .102's shared busy gate when available.

    If the gate cannot be acquired (timeout / service down) the phase continues
    without it, and /busy/down is NOT called so another holder's counter is
    left untouched.
    """
    if not _set_busy("up", stage):
        logger.warning(
            ".102 busy gate unavailable; continuing without it (stage=%s)", stage
        )
        return operation(*args, **kwargs)
    try:
        return operation(*args, **kwargs)
    finally:
        _set_busy("down", stage)
