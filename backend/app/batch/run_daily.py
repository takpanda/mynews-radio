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
from app.batch.review_script import review_script            # noqa: E402
from app.batch.synthesize_voicevox import synthesize_episode as synthesize_voicevox  # noqa: E402
from app.batch.build_episode import build_episode           # noqa: E402
from app.batch.health_check import run_health_checks         # noqa: E402
from app.logging_config import setup_daily_logging           # noqa: E402
from app.config import get_settings                          # noqa: E402
from app.services.episode_service import EpisodeService      # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    # Shared daily log: data/logs/YYYY-MM-DD.log
    setup_daily_logging(__name__, level=logging.INFO)
    logger.info("=== daily batch start (run_daily.py) ===")

    settings = get_settings()

    # Pre-flight health checks for Ollama and the default TTS engine
    health_results = run_health_checks(
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        tts_url=settings.aivispeech_base_url if settings.default_tts_engine == "aivispeech" else settings.voicevox_base_url,
        tts_engine=settings.default_tts_engine,
    )

    if not all(r.status == "ok" for r in health_results):
        failed = [r.service for r in health_results if r.status != "ok"]
        logger.error("Service(s) unhealthy: %s — continuing but risks failure", ", ".join(failed))

    # date for today's episode record
    if os.environ.get("BATCH_DATE"):
        episode_date = os.environ["BATCH_DATE"]  # allow override for testing
    else:
        episode_date = dt.date.today().isoformat()  # YYYY-MM-DD

    episode_service = EpisodeService()
    episode_id = episode_service.create_episode(
        episode_date=episode_date,
        status="generating",
    )
    episode_dir = os.path.join("data", "episodes", str(episode_id))
    os.makedirs(episode_dir, exist_ok=True)
    summaries_path = os.path.join(episode_dir, "summaries.json")

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
        episode_service.update_episode_status(episode_id, "failed")
        _write_manifest(status=f"error_summarize: {exc}")
        sys.exit(1)

    # Step 2: generate script
    script_path = os.path.join(episode_dir, "script.json")
    try:
        line_count = generate_script(script_path)
        logger.info("generated script with %d lines", line_count)
        if line_count == 0:
            logger.warning("Script generation returned 0 lines - aborting pipeline")
            episode_service.update_episode_status(episode_id, "failed")
            _write_manifest(status="skipped_no_scripts")
            sys.exit(0)
    except Exception as exc:
        logger.error("generate_script failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_generate_script: {exc}")
        sys.exit(1)

    # Step 3: synthesize voice
    try:
        wav_count = synthesize_voicevox(episode_dir)
        logger.info("synthesized %d lines", wav_count)
        if wav_count == 0:
            logger.warning("Voice synthesis returned 0 lines - aborting pipeline")
            episode_service.update_episode_status(episode_id, "failed")
            _write_manifest(status="skipped_no_synthesis")
            sys.exit(0)
    except Exception as exc:
        logger.error("synthesize_voicevox failed: %s", exc, exc_info=True)
        _write_manifest(status=f"error_synthesize: {exc}")
        sys.exit(1)

    # Step 4: build episode (combine + mp3)
    try:
        metadata = build_episode(episode_dir)
        if not metadata:
            logger.error("build_episode returned empty metadata - pipeline failed")
            episode_service.update_episode_status(episode_id, "failed")
            _write_manifest(status="error_build")
            sys.exit(1)
    except Exception as exc:
        logger.error("build_episode failed: %s", exc, exc_info=True)
        episode_service.update_episode_status(episode_id, "failed")
        _write_manifest(status=f"error_build: {exc}")
        sys.exit(1)

    # done
    episode_service.update_episode_audio_path(episode_id, metadata.get("audio_path", ""))
    episode_service.update_episode_status(episode_id, "completed")
    logger.info(
        "=== daily batch complete - %s ===",
        metadata.get("title", episode_dir),
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    _write_manifest(status="done", metadata=metadata)

    # --- Reviewed episode (non-fatal; runs after main pipeline succeeds) ---
    logger.info("=== review_script: creating reviewed episode ===")
    reviewed_episode_id: int | None = None
    try:
        reviewed_episode_id = episode_service.create_episode(
            episode_date=episode_date,
            status="generating",
        )
        reviewed_episode_dir = os.path.join("data", "episodes", str(reviewed_episode_id))
        os.makedirs(os.path.join(reviewed_episode_dir, "lines"), exist_ok=True)

        review_result = review_script(script_path, reviewed_episode_dir)
        logger.info(
            "review_script: revised=%s review_count=%d",
            review_result["revised"],
            review_result["review_count"],
        )

        if review_result.get("revised") and review_result.get("lines_count", 0) > 0:
            reviewed_wav = synthesize_voicevox(reviewed_episode_dir)
            logger.info("reviewed synthesize: lines=%d", reviewed_wav)
            if reviewed_wav == 0:
                raise RuntimeError("reviewed synthesize produced 0 WAV files")

            reviewed_meta = build_episode(reviewed_episode_dir)
            if not reviewed_meta:
                raise RuntimeError("reviewed build_episode returned empty metadata")

            episode_service.update_episode_audio_path(reviewed_episode_id, reviewed_meta.get("audio_path", ""))
            episode_service.update_episode_status(reviewed_episode_id, "completed")
            logger.info(
                "=== reviewed episode completed: id=%d duration=%.1fs ===",
                reviewed_episode_id,
                reviewed_meta.get("duration_seconds", 0),
            )
        else:
            logger.warning("review_script did not produce a revised script; marking reviewed episode as failed")
            episode_service.update_episode_status(reviewed_episode_id, "failed")

    except Exception as _rev_exc:
        logger.warning("Reviewed episode failed (non-fatal): %s", _rev_exc, exc_info=True)
        if reviewed_episode_id is not None:
            episode_service.update_episode_status(reviewed_episode_id, "failed")


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
