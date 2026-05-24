#!/usr/bin/env python3
""" daily batch orchestration script

Runs the full pipeline in order:
    0. health_check   – Ollama / VOICEVOX connectivity check
    1. summarize_articles      – fetch new articles from DB, summarize via Ollama
    2. generate_script         – draft a radio script from summaries
    3. synthesize_voicevox     – convert lines to WAV with VoiceVox
    4. build_episode           – combine WAVs -> episode.mp3 + metadata.json

All steps write their logs to data/logs/YYYY-MM-DD.log so cron can pipe output there.
"""
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.summarize_articles import summarize_articles  # noqa: E402
from app.batch.generate_script import generate_script        # noqa: E402
from app.batch.synthesize_voicevox import synthesize_episode as synthesize_voicevox  # noqa: E402
from app.batch.build_episode import build_episode           # noqa: E402
from app.batch.health_check import run_health_checks         # noqa: E402
from app.logging_config import setup_daily_logging           # noqa: E402
from app.config import get_settings                          # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    # Shared daily log: data/logs/YYYY-MM-DD.log
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== daily batch start (run_daily.py) ===")

    settings = get_settings()

    # Pre-flight health checks for Ollama, VOICEVOX
    health_results = run_health_checks(
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        voicevox_url=settings.voicevox_base_url,
    )

    if not all(r.status == "ok" for r in health_results):
        failed = [r.service for r in health_results if r.status != "ok"]
        logger.error("Service(s) unhealthy: %s — continuing but risks failure", ", ".join(failed))

    # date for today's episode directory
    if os.environ.get("BATCH_DATE"):
        episode_date = os.environ["BATCH_DATE"]  # allow override for testing
    else:
        episode_date = dt.date.today().isoformat()  # YYYY-MM-DD

    episodes_dir = os.path.join("data", "episodes", episode_date)
    os.makedirs(episodes_dir, exist_ok=True)
    summaries_path = os.path.join("data", "summaries", "summaries.json")

    # Step 1: summarize articles
    try:
        count = summarize_articles(summaries_path)
        logger.info("summarized %d articles", count)
        if count == 0:
            logger.warning("No new articles to summarize - aborting pipeline")
            _write_manifest(status="skipped_no_new")
            sys.exit(0)
    except Exception as exc:
        logger.error("summarize failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_summarize: {exc}")
        sys.exit(1)

    # Step 2: generate script
    script_path = os.path.join(episodes_dir, "script.json")
    try:
        line_count = generate_script(script_path)
        logger.info("generated script with %d lines", line_count)
        if line_count == 0:
            logger.warning("Script generation returned 0 lines - aborting pipeline")
            _write_manifest(status="skipped_no_scripts")
            sys.exit(0)
    except Exception as exc:
        logger.error("generate_script failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_generate_script: {exc}")
        sys.exit(1)

    # Step 3: synthesize voice
    try:
        wav_count = synthesize_voicevox(episodes_dir)
        logger.info("synthesized %d lines", wav_count)
        if wav_count == 0:
            logger.warning("Voice synthesis returned 0 lines - aborting pipeline")
            _write_manifest(status="skipped_no_synthesis")
            sys.exit(0)
    except Exception as exc:
        logger.error("synthesize_voicevox failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_synthesize: {exc}")
        sys.exit(1)

    # Step 4: build episode (combine + mp3)
    try:
        metadata = build_episode(episodes_dir)
        if not metadata:
            logger.error("build_episode returned empty metadata - pipeline failed")
            _write_manifest(status="error_build")
            sys.exit(1)
    except Exception as exc:
        logger.error("build_episode failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_build: {exc}")
        sys.exit(1)

    # done
    logger.info(
        "=== daily batch complete - %s ===",
        metadata.get("title", episodes_dir),
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    _write_manifest(status="done", metadata=metadata)


def _write_manifest(status: str = "", metadata: dict | None = None) -> None:
    """Persist last-run info as /app/data/run_manifest.json."""
    manifest_path = "/app/data/run_manifest.json"
    payload = {"status": status}
    if metadata:
        payload["metadata"] = metadata
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
