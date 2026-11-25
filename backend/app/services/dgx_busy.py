"""Best-effort shared busy gate for the .102 generation services."""

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")
_DOWN_ATTEMPTS = 3
_DOWN_RETRY_DELAY = 1.0
# Server enforces BUSY_HOLD_LEASE >= 90s (3 intervals of slack).
_HEARTBEAT_INTERVAL = 30.0


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


def _acquire_sequence(stage: str, result: dict, lock: threading.Lock, done: threading.Event) -> None:
    """Worker: up + confirm. Publishes the outcome unless the caller gave up."""
    token = None
    acquired = False
    try:
        settings = get_settings()
        # /busy/up waits until the shared gate is available, which can exceed
        # the normal per-request timeout while a thumbnail renders.
        response = _post_busy("up", settings.dgx_busy_wait_timeout)
        try:
            token = response.json().get("token")
        except Exception:
            token = None
        if token:
            _post_busy("confirm", settings.thumbnail_http_timeout, token)
        acquired = True
    except Exception:
        logger.warning(".102 busy/up request failed (stage=%s)", stage)
    with lock:
        abandoned = result.get("abandoned", False)
        if acquired and not abandoned:
            result["value"] = (True, token)
        else:
            result["value"] = (False, None)
        done.set()
    if (acquired and abandoned) or (token and not acquired):
        # Not handed to the caller (failed, or the caller already gave up):
        # release independently of the phase. By token when there is one
        # (idempotent); a token-less (legacy server) hold is released once the
        # legacy way, which only frees legacy holds on the server.
        _release_busy(stage, token)


def _acquire_busy(stage: str) -> tuple[bool, str | None]:
    """Acquire the gate within one hard deadline (dgx_busy_wait_timeout).

    httpx timeouts apply per read, so a slowly dribbling response could exceed
    them; the whole acquisition therefore runs in a worker and the caller stops
    waiting at the deadline. A claim the worker obtains after that is released
    by the worker. The server also reclaims unconfirmed claims, so a lost
    /busy/up response cannot leak the gate. Servers that return no token (older
    versions) skip the confirmation.
    """
    result: dict = {}
    lock = threading.Lock()
    done = threading.Event()
    threading.Thread(
        target=_acquire_sequence, args=(stage, result, lock, done),
        name="dgx-busy-acquire", daemon=True,
    ).start()
    done.wait(get_settings().dgx_busy_wait_timeout)
    with lock:
        if "value" not in result:
            result["abandoned"] = True
            logger.warning(".102 busy/up exceeded the wait budget (stage=%s)", stage)
            return False, None
        return result["value"]


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


def _heartbeat(stage: str, token: str, stop: threading.Event) -> None:
    """Renew the held claim so a live phase is never reclaimed by the server."""
    while not stop.wait(_HEARTBEAT_INTERVAL):
        try:
            _post_busy("renew", min(get_settings().thumbnail_http_timeout, _HEARTBEAT_INTERVAL), token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.warning(".102 busy claim was reclaimed by the server (stage=%s)", stage)
                return
            logger.warning(".102 busy/renew request failed (stage=%s)", stage)
        except Exception:
            logger.warning(".102 busy/renew request failed (stage=%s)", stage)


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
    stop = threading.Event()
    if token:
        threading.Thread(
            target=_heartbeat, args=(stage, token, stop),
            name="dgx-busy-heartbeat", daemon=True,
        ).start()
    try:
        return operation(*args, **kwargs)
    finally:
        stop.set()
        _release_busy(stage, token)
