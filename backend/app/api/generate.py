"""Broadcast generation endpoint (POST /generate) - async background execution."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.batch.build_episode import build_episode
from app.batch.generate_script import generate_script
from app.batch.import_articles import import_articles_by_source
from app.batch.review_script import review_script
from app.batch.summarize_articles import summarize_articles
from app.batch.synthesize_voicevox import synthesize_episode
from app.config import get_settings
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")


class GenerateRequest(BaseModel):
    date: str = Field(description="放送日 (YYYY-MM-DD)")
    max_articles: int = Field(default=10, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)
    news_source: str = Field(default="hatena_bookmark", description="ニュースソース (hatena_bookmark | hatena_hotentry_all | yahoo_news)")
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech)")
    enable_review: bool = Field(default=True, description="レビューステップを有効にする")
    recreate_summary: bool = Field(default=False, description="既存の要約を再作成するかどうか")


def _run_generation(episode_id: int, body: GenerateRequest) -> None:
    """Background pipeline that persists DB records and status transitions synchronously."""

    service = EpisodeService()
    episode_date = body.date
    base_dir = os.path.join(DEFAULT_EPISODES_DIR, str(episode_id))

    Path(base_dir).mkdir(parents=True, exist_ok=True)

    news_source = body.news_source if body.news_source in {"hatena_bookmark", "hatena_hotentry_all", "yahoo_news"} else "hatena_bookmark"
    program_name = "テックニュース" if news_source == "hatena_bookmark" else "ニュースのとなり"

    logger.info("Background generation started: episode_id=%d date=%s", episode_id, episode_date)

    # -- START --
    service.update_episode_phase(episode_id, "start")
    logger.info("[%d] phase=start", episode_id)

    # -- IMPORT --
    service.update_episode_phase(episode_id, "import")
    try:
        ins, dup = import_articles_by_source(news_source)
        logger.info("RSS import done: inserted=%d duplicated=%d", ins, dup)
    except Exception as exc:
        logger.exception("RSS import failed")
        service.update_episode_status(episode_id, "failed")
        return

    if ins == 0 and dup == 0:
        service.update_episode_status(episode_id, "failed")
        return

    summarize = body.recreate_summary
    if not summarize:
        # 明示的に再作成しない場合でも、new状態の記事があれば要約を実行する
        from app.services.article_service import ArticleService
        check_service = ArticleService()
        new_articles = check_service.fetch_new_articles()
        if new_articles:
            logger.info("Found %d new articles, auto-summarizing", len(new_articles))
            summarize = True

    if summarize:
        yield _format_sse("progress", _build_progress_payload("summarize", "記事を要約しています..."))
        try:
            summaries_path = os.path.join(base_dir, "summaries.json")
            summarized = summarize_articles(summaries_path)
            logger.info("summarize done: count=%d", summarized)
        except Exception as exc:
            logger.exception("summarize failed")
            service.update_episode_status(episode_id, "failed")
            yield _format_sse("error", _build_error_payload(f"記事の要約に失敗しました: {exc}"))
            return
    else:
        logger.info("Skipping summarization step (no new articles)")

    old_max = os.environ.get("MAX_SCRIPT_ARTICLES")
    os.environ["MAX_SCRIPT_ARTICLES"] = str(body.max_articles)

    try:
        # -- GENERATE SCRIPT --
        service.update_episode_phase(episode_id, "generate_script")
        script_path = os.path.join(base_dir, "script.json")
        line_count = generate_script(script_path, program_name=program_name, news_source=news_source)
    finally:
        if old_max is None:
            os.environ.pop("MAX_SCRIPT_ARTICLES", None)
        else:
            os.environ["MAX_SCRIPT_ARTICLES"] = old_max

    if line_count <= 0:
        service.update_episode_status(episode_id, "failed")
        return

    # -- TTS SETUP --
    settings = get_settings()
    tts_engines = {"voicevox", "aivispeech"}
    tts_engine = body.tts_engine if body.tts_engine in tts_engines else settings.default_tts_engine
    if tts_engine == "aivispeech":
        tts_base_url = settings.aivispeech_base_url
        tts_speaker_male = settings.aivispeech_speaker_male
        tts_speaker_female = settings.aivispeech_speaker_female
    else:
        tts_base_url = settings.voicevox_base_url
        tts_speaker_male = settings.voicevox_speaker_male
        tts_speaker_female = settings.voicevox_speaker_female

    reviewed_episode_id: int | None = None
    reviewed_episode_dir: str | None = None
    review_result: dict[str, Any] = {"revised": False, "review_count": 0}

    # -- REVIEW (optional) --
    if body.enable_review:
        service.update_episode_phase(episode_id, "review")
        try:
            reviewed_episode_id = service.create_episode(
                episode_date=episode_date, status="generating"
            )
            reviewed_episode_dir = os.path.join(
                DEFAULT_EPISODES_DIR, str(reviewed_episode_id)
            )
            Path(reviewed_episode_dir).mkdir(parents=True, exist_ok=True)
            Path(os.path.join(reviewed_episode_dir, "lines")).mkdir(exist_ok=True)
            review_result = review_script(script_path, reviewed_episode_dir)
            logger.info(
                "review_script: revised=%s review_count=%d",
                review_result["revised"],
                review_result["review_count"],
            )
            service.update_episode_phase(episode_id, "review_done")
        except Exception as exc:
            logger.warning("review_script failed (non-fatal): %s", exc)
            if reviewed_episode_id is not None:
                service.update_episode_status(reviewed_episode_id, "failed")

    # -- SYNTHESIZE TTS --
    service.update_episode_phase(episode_id, "synthesize")
    try:
        success_count = synthesize_episode(
            base_dir,
            base_url=tts_base_url,
            speaker_male=tts_speaker_male,
            speaker_female=tts_speaker_female,
        )
    except Exception as exc:
        logger.exception("tts synthesis failed")
        service.update_episode_status(episode_id, "failed")
        return

    if success_count <= 0:
        service.update_episode_status(episode_id, "failed")
        return

    # -- BUILD MP3 --
    service.update_episode_phase(episode_id, "build")
    ep_metadata = build_episode(base_dir)
    if not ep_metadata:
        service.update_episode_status(episode_id, "failed")
        return

    service.update_episode_audio_path(
        episode_id, ep_metadata.get("audio_path") or ""
    )
    service.update_episode_status(episode_id, "completed")

    # -- PERSIST ITEMS --
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        for idx, line in enumerate(script.get("lines", []), start=1):
            aid = line.get("article_id")
            service.add_episode_item(
                episode_id=episode_id,
                article_id=int(aid) if aid is not None else None,
                item_order=idx,
                segment_text=line.get("text", ""),
            )
    except Exception:
        logger.exception("failed to persist episode_items")

    # -- BUILD REVIEWED EPISODE (non-fatal) --
    if reviewed_episode_id is not None and reviewed_episode_dir is not None:
        if review_result.get("revised"):
            try:
                reviewed_wav = synthesize_episode(
                    reviewed_episode_dir,
                    base_url=tts_base_url,
                    speaker_male=tts_speaker_male,
                    speaker_female=tts_speaker_female,
                )
                if reviewed_wav <= 0:
                    raise RuntimeError("reviewed synthesize produced 0 WAV files")

                reviewed_meta = build_episode(reviewed_episode_dir)
                if not reviewed_meta:
                    raise RuntimeError(
                        "reviewed build_episode returned empty metadata"
                    )

                service.update_episode_audio_path(
                    reviewed_episode_id,
                    reviewed_meta.get("audio_path") or "",
                )
                service.update_episode_status(reviewed_episode_id, "completed")
            except Exception as exc:
                logger.warning(
                    "Reviewed episode build failed (non-fatal): %s", exc
                )
                service.update_episode_status(reviewed_episode_id, "failed")
        else:
            service.update_episode_status(reviewed_episode_id, "failed")

    service.update_episode_phase(episode_id, "complete")
    logger.info("[%d] completed successfully", episode_id)


@router.post("/generate", summary="番組を生成する（バックグラウンド実行）")
def generate_episode(body: GenerateRequest) -> dict:
    """Creates episode record and returns JSON immediately; actual generation runs in background."""

    service = EpisodeService()

    # Check for existing generating episode on the same date to avoid duplicates
    episodes = service.get_episode_list()
    for ep in episodes:
        if ep["episode_date"] == body.date and ep["status"] == "generating":
            raise HTTPException(
                status_code=409,
                detail=f"Episode for {body.date} is already generating (id={ep['id']})",
            )

    # Create the episode record once - background task reuses this same id
    episode_id = service.create_episode(
        episode_date=body.date, status="generating"
    )
    service.update_episode_phase(episode_id, "start")

    # Start actual pipeline in background; prefer asyncio under uvicorn
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop is not None:
        asyncio.ensure_future(_async_wrapper(episode_id, body))
    else:
        import threading as _th
        t = _th.Thread(target=_run_generation, args=(episode_id, body), daemon=True)
        t.start()

    return {
        "episode_id": episode_id,
        "status": "generating",
        "message": f"Episode generation started for {body.date}",
    }


async def _async_wrapper(episode_id: int, body: GenerateRequest) -> None:
    """Run synchronous pipeline in a thread to not block the event loop."""
    await asyncio.to_thread(_run_generation, episode_id, body)

