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
            timeout=settings.thumbnail_http_timeout,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(".102 busy/%s request failed (stage=%s)", endpoint, stage)
        return False


def run_with_dgx_busy(stage: str, operation: Callable[..., T], *args, **kwargs) -> T:
    """Run one LLM/TTS phase while holding .102's counter, without failing closed."""
    _set_busy("up", stage)
    try:
        return operation(*args, **kwargs)
    finally:
        _set_busy("down", stage)
