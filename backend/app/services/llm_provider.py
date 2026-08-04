"""LLM provider configuration and model discovery.

Credentials and endpoint details are deliberately kept server-side.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

PROVIDERS = ("ollama", "lm_studio", "vllm")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    native: bool = False
    api_key: str = ""


def provider_configs() -> dict[str, ProviderConfig]:
    s = get_settings()
    return {
        "ollama": ProviderConfig("ollama", s.ollama_base_url, s.ollama_model, True),
        "lm_studio": ProviderConfig("lm_studio", s.lm_studio_base_url, s.lm_studio_model, False, s.lm_studio_api_key),
        "vllm": ProviderConfig("vllm", s.vllm_base_url, s.vllm_model, False, s.vllm_api_key),
    }


def validate_provider_model(provider: str | None, model: str | None) -> ProviderConfig:
    name = provider or get_settings().llm_provider
    config = provider_configs().get(name)
    if config is None:
        raise ValueError("unsupported llm provider")
    selected = model or config.model
    if not selected:
        raise ValueError("llm model is not configured")
    # A configured default is an explicit server-side allow-list entry. For a
    # request override, require a successful discovery result (or a recent
    # successful result kept for stale operation) before accepting it.
    if selected != config.model:
        now = time.monotonic()
        cached = _cache.get(name)
        discovered = cached[1].get("models", []) if cached and cached[1].get("available") else []
        if not discovered and name in _last_success and now - _last_success[name][0] < 600:
            discovered = _last_success[name][1].get("models", [])
        if selected not in discovered:
            if cached is None or (not cached[1].get("available") and name not in _last_success):
                try:
                    fetched = asyncio.run(_fetch(config))
                except RuntimeError:
                    fetched = {"available": False, "models": []}
                _cache[name] = (now, fetched)
                if fetched.get("available"):
                    _last_success[name] = (now, fetched)
                    discovered = fetched.get("models", [])
            if selected not in discovered:
                raise ValueError("model is not available for provider")
    return ProviderConfig(config.name, config.base_url, selected, config.native, config.api_key)


def _timeout() -> httpx.Timeout:
    s = get_settings()
    return httpx.Timeout(s.llm_response_timeout, connect=s.llm_connect_timeout)


async def _fetch(config: ProviderConfig) -> dict[str, Any]:
    try:
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        async with httpx.AsyncClient(base_url=config.base_url.rstrip("/"), timeout=_timeout(), headers=headers) as client:
            if config.native:
                response = await client.get("/api/tags")
                response.raise_for_status()
                models = [m.get("name") for m in response.json().get("models", []) if m.get("name")]
            else:
                response = await client.get("/v1/models")
                response.raise_for_status()
                models = [m.get("id") for m in response.json().get("data", []) if m.get("id")]
            return {"provider": config.name, "models": models, "available": True}
    except httpx.TimeoutException:
        return {"provider": config.name, "models": [], "available": False, "error_code": "timeout"}
    except httpx.ConnectError:
        return {"provider": config.name, "models": [], "available": False, "error_code": "connection_failed"}
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        return {"provider": config.name, "models": [], "available": False, "error_code": "invalid_response"}
    except httpx.HTTPError:
        return {"provider": config.name, "models": [], "available": False, "error_code": "connection_failed"}
    except Exception:
        return {"provider": config.name, "models": [], "available": False, "error_code": "connection_failed"}


_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_last_success: dict[str, tuple[float, dict[str, Any]]] = {}


async def discover_providers() -> dict[str, Any]:
    now = time.monotonic()
    configs = provider_configs()
    results: list[dict[str, Any]] = []
    pending = []
    for name, config in configs.items():
        cached = _cache.get(name)
        # Successful discovery is cached for 60s; failures only for 10s so a
        # provider recovering from a restart is noticed promptly.
        cache_ttl = 10 if cached and cached[1].get("stale") else (60 if cached and cached[1].get("available") else 10)
        if cached and now - cached[0] < cache_ttl:
            results.append(cached[1])
        else:
            pending.append((name, config))
    fetched = await asyncio.gather(*(_fetch(c) for _, c in pending))
    for result in fetched:
        name = result["provider"]
        _cache[name] = (now, result)
        if result["available"]:
            _last_success[name] = (now, result)
        elif name in _last_success and now - _last_success[name][0] < 600:
            result = {**_last_success[name][1], "stale": True}
            # Keep serving the bounded stale result during the short failure
            # cache window instead of exposing a transient empty response.
            _cache[name] = (now, result)
        results.append(result)
    results.sort(key=lambda item: PROVIDERS.index(item["provider"]))
    # APIレスポンスには固定の状態コードだけを返し、接続先や例外は返さない。
    safe_results: list[dict[str, Any]] = []
    for result in results:
        safe = {
            "provider": result.get("provider"),
            "models": result.get("models", []) if isinstance(result.get("models", []), list) else [],
            "available": bool(result.get("available")),
        }
        if result.get("stale"):
            safe["stale"] = True
        if not safe["available"]:
            error_code = result.get("error_code", "connection_failed")
            safe["error_code"] = error_code if error_code in {"timeout", "connection_failed", "invalid_response"} else "connection_failed"
        else:
            safe.pop("error_code", None)
        safe_results.append(safe)
    return {"providers": safe_results}


def clear_provider_cache() -> None:
    _cache.clear()
    _last_success.clear()
