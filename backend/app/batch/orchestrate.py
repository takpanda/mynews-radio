#!/usr/bin/env python3
"""
Batch orchestration script for MyNews Radio episode generation.

Runs 5 steps sequentially:
    import_articles → summarize_articles → generate_script → review_script → synthesize_voicevox → build_episode

On any step failure, remaining steps are skipped and the episode status is set to `failed`.
Intermediate artifacts are preserved on error.
If articles.json does not exist, a WARNING is logged and processing stops (status remains unchanged).
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.db.connection import get_db_connection
from app.batch.import_articles import import_articles, import_articles_by_source
from app.batch.summarize_articles import summarize_articles
from app.batch.generate_script import generate_script
from app.batch.review_script import review_script
from app.batch.synthesize_voicevox import synthesize_episode
from app.batch.build_episode import build_episode
from app.services.article_service import ArticleService
from app.services.episode_service import EpisodeService, retry_on_busy, override_script_title, build_radio_title

logger = logging.getLogger(__name__)

# --- Configuration (convention: env vars with sensible defaults) ---

EPISODES_DIR = os.getenv("EPISODES_DIR", os.path.join("data", "episodes"))
ARTICLES_JSON = os.getenv("ARTICLES_JSON", os.path.join("data", "articles", "articles.json"))


# ---------------------------------------------------------------------------
# DB helpers (minimal, avoids pulling in episode_service with its own defaults)
# ---------------------------------------------------------------------------

def _set_episode_status(episode_id: int, status: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, episode_id),
        )


@retry_on_busy()
def _create_episode_record(date_str: str) -> tuple[int, int]:
    ep_service = EpisodeService()
    return ep_service.create_radio_episode(episode_date=date_str, status="generating")


def _update_episode_audio(episode_id: int, audio_path: str) -> None:
    ep_service = EpisodeService()
    ep_service.update_episode_audio_path(episode_id, audio_path)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(date_str: str | None = None, news_source: str = "hatena_bookmark") -> None:
    if date_str is None:
        from datetime import date as _date
        date_str = str(_date.today())

    # Create episode DB record with status=generating
    ep_service = EpisodeService()
    episode_id, seq = _create_episode_record(date_str)
    logger.info("Episode record created: id=%d, date=%s, seq=%d", episode_id, date_str, seq)

    episode_dir = os.path.join(EPISODES_DIR, str(episode_id))
    artifact_dir = os.path.join(episode_dir, "lines")

    # Ensure output directories
    os.makedirs(episode_dir, exist_ok=True)
    os.makedirs(artifact_dir, exist_ok=True)

    try:
        # Step 1: import_articles
        logger.info("=== Step 1/5: import_articles (source=%s) ===", news_source)
        ins, dup = import_articles_by_source(news_source)
        logger.info("import_articles completed: inserted=%d duplicated=%d", ins, dup)
        if ins == 0 and dup == 0:
            raise RuntimeError("import_articles processed 0 articles")

        # Step 2: summarize_articles
        logger.info("=== Step 2/5: summarize_articles ===")
        summaries_path = os.path.join(episode_dir, "summaries.json")
        summarized = summarize_articles(summaries_path)
        logger.info("summarize_articles completed: counted=%d", summarized)
        if summarized == 0:
            article_service = ArticleService()
            max_articles = int(os.getenv("MAX_SCRIPT_ARTICLES", "10"))
            min_score = int(os.getenv("MIN_IMPORTANCE_SCORE", "3"))
            existing_summaries = article_service.fetch_summaries_for_script(
                max_articles=max_articles,
                min_importance_score=min_score,
                source=news_source,
            )
            if not existing_summaries:
                raise RuntimeError("summarize_articles produced no results")
            logger.info(
                "No new articles to summarize, but %d existing summarized articles are available. Continuing.",
                len(existing_summaries),
            )

        # Step 3: generate_script
        logger.info("=== Step 3/5: generate_script (source=%s) ===", news_source)
        script_path = os.path.join(episode_dir, "script.json")
        program_name = "テックニュース" if news_source == "hatena_bookmark" else "ニュースのとなり"
        lines_count = generate_script(script_path, program_name=program_name, news_source=news_source)
        logger.info("generate_script completed: lines=%d", lines_count)
        if lines_count == 0:
            raise RuntimeError("generate_script produced no lines")

        # Override title with date-based format
        override_script_title(script_path, program_name, date_str, seq)
        logger.info("Title overridden: %s", build_radio_title(program_name, date_str, seq))

        # Step 4: review_script — quality gate (non-fatal)
        logger.info("=== Step 4/5: review_script (quality gate) ===")
        review_result: dict = {"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0}
        try:
            reviewed_episode_dir = os.path.join(episode_dir, "review")
            Path(reviewed_episode_dir).mkdir(parents=True, exist_ok=True)
            Path(os.path.join(reviewed_episode_dir, "lines")).mkdir(exist_ok=True)

            review_result = review_script(script_path, reviewed_episode_dir)
            logger.info(
                "review_script completed: revised=%s review_count=%d",
                review_result["revised"],
                review_result["review_count"],
            )

            if review_result.get("revised"):
                shutil.copy(os.path.join(reviewed_episode_dir, "script.json"), script_path)
                override_script_title(script_path, program_name, date_str, seq)
                logger.info("Reviewed script copied to production script.json")
        except Exception as _rev_exc:
            logger.warning("review_script failed (non-fatal): %s", _rev_exc)

        # Step 5: synthesize_voicevox
        logger.info("=== Step 5/5: synthesize_voicevox ===")
        wave_count = synthesize_episode(episode_dir)
        logger.info("synthesize_voicevox completed: lines=%d", wave_count)
        if wave_count == 0:
            raise RuntimeError("synthesize_voicevox produced no WAV files")

        # Step 5: build_episode
        logger.info("=== Step 5/5: build_episode (episode) ===")
        metadata = build_episode(episode_dir)
        if not metadata:
            raise RuntimeError("build_episode returned empty metadata")

        _update_episode_audio(episode_id, "episode.mp3")
        _set_episode_status(episode_id, "done")

        logger.info("=== Episode generation completed successfully ===")
        logger.info("Episode ID: %d  |  Date: %s  |  Audio: episode.mp3  |  Duration: %.1fs",
                     episode_id, date_str, metadata.get("duration_seconds", 0))

    except SystemExit as exc:
        # Catch sys.exit() from batch modules (they exit 0 on success, 1 on failure)
        if getattr(exc, "code", 0) != 0:
            logger.error("Batch step exited with code %s — aborting remaining steps", exc.code)
            _set_episode_status(episode_id, "failed")
            raise
        # Exit code 0 is success; fall through to the next step
        raise

    except Exception as exc:
        logger.exception("Orchestration failed at an intermediate step — setting status=failed")
        _set_episode_status(episode_id, "failed")
        raise


def main() -> None:
    from app.logging_config import setup_daily_logging  # noqa: E402
    setup_daily_logging(__name__, level=logging.INFO)

    from datetime import date as _date  # noqa: E402
    default_date = str(_date.today())
    date_str = sys.argv[1] if len(sys.argv) > 1 else default_date
    news_source = sys.argv[2] if len(sys.argv) > 2 else "hatena_bookmark"
    run(date_str, news_source=news_source)


if __name__ == "__main__":
    main()
