"""LLM provider configuration and model discovery.

Credentials and endpoint details are deliberately kept server-side.
"""
from __future__ import annotations

import asyncio
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


def provider_configs() -> dict[str, ProviderConfig]:
    s = get_settings()
    return {
        "ollama": ProviderConfig("ollama", s.ollama_base_url, s.ollama_model, True),
        "lm_studio": ProviderConfig("lm_studio", s.lm_studio_base_url, s.lm_studio_model),
        "vllm": ProviderConfig("vllm", s.vllm_base_url, s.vllm_model),
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
    return ProviderConfig(config.name, config.base_url, selected, config.native)


def _timeout() -> httpx.Timeout:
    s = get_settings()
    return httpx.Timeout(s.llm_response_timeout, connect=s.llm_connect_timeout)


async def _fetch(config: ProviderConfig) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(base_url=config.base_url.rstrip("/"), timeout=_timeout()) as client:
            if config.native:
                response = await client.get("/api/tags")
                response.raise_for_status()
                models = [m.get("name") for m in response.json().get("models", []) if m.get("name")]
            else:
                response = await client.get("/v1/models")
                response.raise_for_status()
                models = [m.get("id") for m in response.json().get("data", []) if m.get("id")]
            return {"provider": config.name, "models": models, "available": True}
    except Exception:
        return {"provider": config.name, "models": [], "available": False}


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
    return {"providers": results}


def clear_provider_cache() -> None:
    _cache.clear()
    _last_success.clear()
