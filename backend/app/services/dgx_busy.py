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
            # /busy/up waits until the shared gate is available. Its wait can
            # exceed the normal per-request timeout while a thumbnail renders.
            timeout=None if endpoint == "up" else settings.thumbnail_http_timeout,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(".102 busy/%s request failed (stage=%s)", endpoint, stage)
        return False


def run_with_dgx_busy(stage: str, operation: Callable[..., T], *args, **kwargs) -> T:
    """Run one LLM/TTS phase only after acquiring .102's shared busy gate."""
    if not _set_busy("up", stage):
        raise RuntimeError(f"Failed to acquire .102 busy gate for stage={stage}")
    try:
        return operation(*args, **kwargs)
    finally:
        _set_busy("down", stage)
