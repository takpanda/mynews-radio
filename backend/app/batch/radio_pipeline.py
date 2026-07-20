"""Shared radio generation pipeline - used by both Web UI and Batch."""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from app.batch.build_episode import build_episode
from app.batch.generate_script import generate_script
from app.batch.import_articles import import_articles_by_source
from app.batch.review_script import review_script
from app.batch.summarize_articles import summarize_articles
from app.batch.synthesize_voicevox import synthesize_episode
from app.config import get_settings
from app.services.episode_service import EpisodeService, override_script_title, build_radio_title

logger = logging.getLogger(__name__)

DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")

ProgressCallback = Optional[Callable[[str, str], None]]


def _determine_tts_config(tts_engine: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    tts_engines = {"voicevox", "aivispeech"}
    engine = tts_engine if tts_engine and tts_engine in tts_engines else settings.default_tts_engine
    if engine == "aivispeech":
        return {
            "tts_engine": engine,
            "base_url": settings.aivispeech_base_url,
            "speaker_male": settings.aivispeech_speaker_male,
            "speaker_female": settings.aivispeech_speaker_female,
        }
    return {
        "tts_engine": engine,
        "base_url": settings.voicevox_base_url,
        "speaker_male": settings.voicevox_speaker_male,
        "speaker_female": settings.voicevox_speaker_female,
    }


def run_radio_pipeline(
    episode_id: int,
    *,
    episode_date: str,
    news_source: str = "hatena_bookmark",
    program_name: str | None = None,
    seq: int = 0,
    max_articles: int = 10,
    tts_engine: str | None = None,
    tts_base_url: str | None = None,
    tts_speaker_male: int | None = None,
    tts_speaker_female: int | None = None,
    default_episodes_dir: str | None = None,
    progress_callback: ProgressCallback = None,
) -> dict[str, Any] | None:
    """Run the full radio generation pipeline for an episode.

    Returns metadata dict on success, None on failure.
    Episode status is updated to "completed" on success or "failed" on error.
    """
    service = EpisodeService()
    base_dir = (default_episodes_dir or DEFAULT_EPISODES_DIR)
    base_dir = os.path.join(base_dir, str(episode_id))
    effective_program_name = program_name or (
        "テックニュース" if news_source == "hatena_bookmark" else "ニュースのとなり"
    )

    Path(base_dir).mkdir(parents=True, exist_ok=True)

    def _progress(phase: str, message: str) -> None:
        if progress_callback:
            progress_callback(phase, message)
        logger.info("[%d] phase=%s %s", episode_id, phase, message)

    try:
        _progress("start", "番組の生成を準備しています…")

        # -- IMPORT --
        _progress("import", "ニュース記事を取得しています…")
        try:
            ins, dup = import_articles_by_source(news_source)
            logger.info("RSS import done: inserted=%d duplicated=%d", ins, dup)
        except Exception as exc:
            logger.exception("RSS import failed")
            service.update_episode_status(episode_id, "failed")
            return None

        if ins == 0 and dup == 0:
            service.update_episode_status(episode_id, "failed")
            return None

        # -- SUMMARIZE --
        _progress("summarize", "記事を要約しています…")
        try:
            summaries_path = os.path.join(base_dir, "summaries.json")
            summarized = summarize_articles(summaries_path)
            logger.info("summarize done: count=%d", summarized)
        except Exception as exc:
            logger.exception("summarize failed")
            service.update_episode_status(episode_id, "failed")
            return None

        # -- GENERATE SCRIPT --
        old_max = os.environ.get("MAX_SCRIPT_ARTICLES")
        os.environ["MAX_SCRIPT_ARTICLES"] = str(max_articles)
        try:
            _progress("generate_script", "台本を生成しています…")
            script_path = os.path.join(base_dir, "script.json")
            line_count = generate_script(
                script_path,
                program_name=effective_program_name,
                news_source=news_source,
            )
        finally:
            if old_max is None:
                os.environ.pop("MAX_SCRIPT_ARTICLES", None)
            else:
                os.environ["MAX_SCRIPT_ARTICLES"] = old_max

        if line_count <= 0:
            service.update_episode_status(episode_id, "failed")
            return None

        override_script_title(script_path, effective_program_name, episode_date, seq)
        logger.info("Title overridden: %s", build_radio_title(effective_program_name, episode_date, seq))

        # -- TTS SETUP --
        if tts_base_url is not None and tts_speaker_male is not None and tts_speaker_female is not None:
            effective_tts_base_url = tts_base_url
            effective_tts_male = tts_speaker_male
            effective_tts_female = tts_speaker_female
        else:
            tts_config = _determine_tts_config(tts_engine)
            effective_tts_base_url = tts_config["base_url"]
            effective_tts_male = tts_config["speaker_male"]
            effective_tts_female = tts_config["speaker_female"]

        review_result: dict[str, Any] = {"revised": False, "review_count": 0}

        # -- REVIEW (quality gate) --
        _progress("review", "台本をレビューしています…")
        try:
            reviewed_episode_dir = os.path.join(base_dir, "review")
            Path(reviewed_episode_dir).mkdir(parents=True, exist_ok=True)
            Path(os.path.join(reviewed_episode_dir, "lines")).mkdir(exist_ok=True)
            review_result = review_script(script_path, reviewed_episode_dir)
            logger.info(
                "review_script: revised=%s review_count=%d",
                review_result["revised"],
                review_result["review_count"],
            )
            _progress("review_done", "レビューが完了しました…")
        except Exception as exc:
            logger.warning("review_script failed (non-fatal): %s", exc)

        # -- BRANCH based on revised flag --
        if review_result.get("revised"):
            shutil.copy(os.path.join(reviewed_episode_dir, "script.json"), script_path)
            override_script_title(script_path, effective_program_name, episode_date, seq)

        # -- SYNTHESIZE TTS --
        _progress("synthesize", "音声を合成しています…")
        try:
            success_count = synthesize_episode(
                base_dir,
                base_url=effective_tts_base_url,
                speaker_male=effective_tts_male,
                speaker_female=effective_tts_female,
            )
        except Exception as exc:
            logger.exception("tts synthesis failed")
            service.update_episode_status(episode_id, "failed")
            return None

        if success_count <= 0:
            service.update_episode_status(episode_id, "failed")
            return None

        # -- BUILD MP3 --
        _progress("build", "音声をまとめています…")
        ep_metadata = build_episode(base_dir)
        if not ep_metadata:
            service.update_episode_status(episode_id, "failed")
            return None

        service.update_episode_audio_path(
            episode_id, ep_metadata.get("audio_path") or ""
        )

        # -- PERSIST ITEMS --
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            for idx, line in enumerate(script.get("lines", []), start=1):
                aid = line.get("article_id")
                audio_generation_id = f"ep{episode_id}-seg{idx}"
                service.add_episode_item(
                    episode_id=episode_id,
                    article_id=int(aid) if aid is not None else None,
                    item_order=idx,
                    segment_text=line.get("text", ""),
                    audio_generation_id=audio_generation_id,
                )
        except Exception:
            logger.exception("failed to persist episode_items")
            service.update_episode_status(episode_id, "failed")
            return None

        service.update_episode_status(episode_id, "completed")
        _progress("complete", "生成が完了しました")
        logger.info("[%d] completed successfully", episode_id)

        return ep_metadata

    except Exception as exc:
        if service is not None:
            current = service.get_episode(episode_id)
            current_status = current["status"] if current else None
            if current_status not in {"completed", "failed"}:
                logger.exception("[%d] generation failed unexpectedly", episode_id)
                service.update_episode_status(episode_id, "failed")
        else:
            logger.exception("[%d] generation failed before service init", episode_id)
        return None
