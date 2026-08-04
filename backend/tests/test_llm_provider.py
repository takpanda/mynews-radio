import asyncio
import time

import pytest

from app.services import llm_provider
from app.services.llm_provider import ProviderConfig


def _configs(monkeypatch):
    monkeypatch.setattr(llm_provider, "provider_configs", lambda: {
        "ollama": ProviderConfig("ollama", "http://ollama.internal:11434", "configured-model", True),
        "lm_studio": ProviderConfig("lm_studio", "http://lm.internal:1234", "", False),
        "vllm": ProviderConfig("vllm", "http://vllm.internal:8000", "", False),
    })
    llm_provider.clear_provider_cache()


def test_model_override_requires_discovered_model(monkeypatch):
    _configs(monkeypatch)
    async def unavailable(config):
        return {"provider": config.name, "models": [], "available": False}
    monkeypatch.setattr(llm_provider, "_fetch", unavailable)
    with pytest.raises(ValueError, match="not available"):
        llm_provider.validate_provider_model("ollama", "unknown")


def test_configured_model_is_allowed_when_provider_unreachable(monkeypatch):
    _configs(monkeypatch)
    result = llm_provider.validate_provider_model("ollama", "configured-model")
    assert result.model == "configured-model"


def test_discovered_override_is_allowed(monkeypatch):
    _configs(monkeypatch)
    monkeypatch.setattr(llm_provider, "_fetch", lambda config: asyncio.sleep(0, result={
        "provider": config.name, "models": ["discovered"], "available": True,
    }))
    assert llm_provider.validate_provider_model("ollama", "discovered").model == "discovered"


def test_provider_result_does_not_expose_endpoint_or_exception(monkeypatch):
    _configs(monkeypatch)
    async def failed(_config):
        return {"provider": "ollama", "models": [], "available": False}
    monkeypatch.setattr(llm_provider, "_fetch", failed)
    result = asyncio.run(llm_provider.discover_providers())
    assert "internal" not in repr(result)
    assert "exception" not in repr(result).lower()
    assert set(result["providers"][0]) <= {"provider", "models", "available", "stale"}


def test_success_cache_and_stale_fallback(monkeypatch):
    _configs(monkeypatch)
    calls = []
    async def fetch(config):
        calls.append(config.name)
        return {"provider": config.name, "models": ["one"], "available": True}
    monkeypatch.setattr(llm_provider, "_fetch", fetch)
    first = asyncio.run(llm_provider.discover_providers())
    second = asyncio.run(llm_provider.discover_providers())
    assert first["providers"][0]["models"] == ["one"]
    assert second["providers"][0]["models"] == ["one"]
    assert calls.count("ollama") == 1

    llm_provider._cache["ollama"] = (time.monotonic() - 61, first["providers"][0])
    async def fail(config):
        calls.append(f"failed:{config.name}")
        return {"provider": config.name, "models": [], "available": False}
    monkeypatch.setattr(llm_provider, "_fetch", fail)
    stale = asyncio.run(llm_provider.discover_providers())
    assert stale["providers"][0]["models"] == ["one"]
    assert stale["providers"][0]["stale"] is True

    # stale fallback is still a failed refresh and must be retried after 10s.
    llm_provider._cache["ollama"] = (time.monotonic() - 11, llm_provider._cache["ollama"][1])
    asyncio.run(llm_provider.discover_providers())
    assert calls.count("failed:ollama") == 2


def test_failure_cache_is_shorter_than_success_cache(monkeypatch):
    _configs(monkeypatch)
    calls = []
    async def fail(config):
        calls.append(config.name)
        return {"provider": config.name, "models": [], "available": False}
    monkeypatch.setattr(llm_provider, "_fetch", fail)
    asyncio.run(llm_provider.discover_providers())
    asyncio.run(llm_provider.discover_providers())
    assert calls.count("ollama") == 1
    llm_provider._cache["ollama"] = (time.monotonic() - 11, llm_provider._cache["ollama"][1])
    asyncio.run(llm_provider.discover_providers())
    assert calls.count("ollama") == 2
