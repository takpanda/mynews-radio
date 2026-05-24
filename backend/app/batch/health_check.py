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


def health_check_voicevox(base_url: str) -> Dict[str, str]:
    """VOICEVOX のヘルスチェックを実行して結果をログに記録する."""
    with VoicevoxClient(base_url) as client:
        result = client.health_check()

    status = result.get("status", "error")
    detail = result.get("detail", "unknown")

    if status == "ok":
        logger.info("VOICEVOX health check OK (url=%s, version=%s)", base_url, detail)
    else:
        logger.error("VOICEVOX health check failed (url=%s): %s", base_url, detail)

    return {"service": "voicevox", "status": status, "detail": detail}


def run_health_checks(
    ollama_url: str, ollama_model: str, voicevox_url: str
) -> List[Dict[str, str]]:
    """Ollama と VOICEVOX の両方のヘルスチェックを実行する."""
    logger.info("=== Health checks start ===")
    logger.info("  Ollama base URL : %s", ollama_url)
    logger.info("  VOICEVOX base URL : %s", voicevox_url)

    ollama_result = health_check_ollama(ollama_url, ollama_model)
    voicevox_result = health_check_voicevox(voicevox_url)
    results = [ollama_result, voicevox_result]

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
    results = run_health_checks(settings.ollama_base_url, settings.ollama_model, settings.voicevox_base_url)
    for r in results:
        print(f" {r['service']}: {r['status']} {r.get('detail', '')}")
