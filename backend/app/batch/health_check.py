#!/usr/bin/env python3
"""Ollama と VOICEVOX のヘルスチェック関数."""

import logging
import sys
from typing import Dict, List

# Ensure backend root is on sys.path (mirrors what batch scripts do).
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", ".."))

from app.services.ollama_client import OllamaClient  # noqa: E402
from app.services.voicevox_client import VoicevoxClient  # noqa: E402

logger = logging.getLogger(__name__)


def health_check_ollama(base_url: str, model: str) -> Dict[str, str]:
    """Ollama のヘルスチェックを実行して結果をログに記録する."""
    with OllamaClient(base_url, model) as client:
        result = client.health_check()

    status = result.get("status", "error")
    detail = "model=" + model if status == "ok" else result.get("detail", "")

    if status == "ok":
        logger.info("Ollama health check OK (url=%s, model=%s)", base_url, model)
    else:
        logger.error("Ollama health check failed (url=%s): %s", base_url, detail)

    return {"service": "ollama", "status": status, "detail": detail}


def health_check_tts(base_url: str, engine: str) -> Dict[str, str]:
    """TTS エンジンのヘルスチェックを実行して結果をログに記録する."""
    with VoicevoxClient(base_url) as client:
        result = client.health_check()

    status = result.get("status", "error")
    detail = result.get("detail", "unknown")

    if status == "ok":
        logger.info("%s health check OK (url=%s, version=%s)", engine.upper(), base_url, detail)
    else:
        logger.error("%s health check failed (url=%s): %s", engine.upper(), base_url, detail)

    return {"service": engine, "status": status, "detail": detail}


def run_health_checks(
    ollama_url: str, ollama_model: str, tts_url: str, tts_engine: str
) -> List[Dict[str, str]]:
    """Ollama と TTS エンジンのヘルスチェックを実行する."""
    logger.info("=== Health checks start ===")
    logger.info("  Ollama base URL : %s", ollama_url)
    logger.info("  TTS base URL : %s", tts_url)
    logger.info("  Default TTS engine : %s", tts_engine)

    ollama_result = health_check_ollama(ollama_url, ollama_model)
    tts_result = health_check_tts(tts_url, tts_engine)
    results = [ollama_result, tts_result]

    all_ok = all(r["status"] == "ok" for r in results)
    if all_ok:
        logger.info("=== Health checks passed ===")
    else:
        failed = [r["service"] for r in results if r["status"] != "ok"]
        logger.error("=== Health checks FAILED for: %s ===", ", ".join(failed))

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    from app.config import get_settings  # noqa: E402

    settings = get_settings()
    tts_url = settings.aivispeech_base_url if settings.default_tts_engine == "aivispeech" else settings.voicevox_base_url
    results = run_health_checks(settings.ollama_base_url, settings.ollama_model, tts_url, settings.default_tts_engine)
    for r in results:
        print(f" {r['service']}: {r['status']} {r.get('detail', '')}")
