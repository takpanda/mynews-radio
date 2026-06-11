"""Broadcast generation endpoint (POST /generate) - async background execution."""

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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

PHASE_SEQUENCE = {
    "start": {"step_index": 0, "step_total": 6, "step_label": "開始"},
    "import": {"step_index": 1, "step_total": 6, "step_label": "記事取得"},
    "summarize": {"step_index": 2, "step_total": 6, "step_label": "要約"},
    "generate_script": {"step_index": 3, "step_total": 6, "step_label": "台本生成"},
    "review": {"step_index": 4, "step_total": 6, "step_label": "レビュー"},
    "review_done": {"step_index": 4, "step_total": 6, "step_label": "レビュー"},
    "synthesize": {"step_index": 5, "step_total": 6, "step_label": "音声合成"},
    "build": {"step_index": 6, "step_total": 6, "step_label": "音声統合"},
    "db": {"step_index": 6, "step_total": 6, "step_label": "保存"},
    "review_synthesize": {"step_index": 6, "step_total": 6, "step_label": "レビュー版音声合成"},
    "review_build": {"step_index": 6, "step_total": 6, "step_label": "レビュー版統合"},
    "review_complete": {"step_index": 6, "step_total": 6, "step_label": "レビュー版完了"},
    "complete": {"step_index": 6, "step_total": 6, "step_label": "完了"},
    "failed": {"step_index": 0, "step_total": 6, "step_label": "失敗"},
}


def _format_sse(event: str, payload: dict) -> bytes:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


def _build_error_payload(message: str, status: str = "error") -> dict:
    payload = {"phase": "failed", "status": status, "message": message}
    payload.update(PHASE_SEQUENCE["failed"])
    return payload


def _build_progress_payload(phase: str, message: str, status: str = "running", **extra: object) -> dict:
    payload = {"phase": phase, "status": status, "message": message}
    payload.update(PHASE_SEQUENCE.get(phase, {"step_index": 0, "step_total": 6, "step_label": phase}))
    payload.update(extra)
    return payload


class GenerateRequest(BaseModel):
    date: str = Field(description="放送日 (YYYY-MM-DD)")
    max_articles: int = Field(default=10, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)
    news_source: str = Field(default="hatena_bookmark", description="ニュースソース (hatena_bookmark | hatena_hotentry_all | yahoo_news)")
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech)")
    enable_review: bool = Field(default=True, description="レビューステップを有効にする")


def _run_generation(episode_id: int, body: GenerateRequest) -> None:
    """Background pipeline that persists DB records and status transitions synchronously."""

    service = None
    try:
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

        # -- SUMMARIZE --
        service.update_episode_phase(episode_id, "summarize")
        try:
            summaries_path = os.path.join(base_dir, "summaries.json")
            summarized = summarize_articles(summaries_path)
            logger.info("summarize done: count=%d", summarized)
        except Exception as exc:
            logger.exception("summarize failed")
            service.update_episode_status(episode_id, "failed")
            return

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
                    episode_date=episode_date, status="pending"
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
    except Exception:
        if service is not None:
            current = service.get_episode(episode_id)
            current_status = current["status"] if current else None
            if current_status not in {"completed", "failed"}:
                logger.exception("[%d] generation failed unexpectedly, marking as failed", episode_id)
                service.update_episode_status(episode_id, "failed")
        else:
            logger.exception("[%d] generation failed before service init", episode_id)


@router.post("/generate", summary="番組を生成する（バックグラウンド実行）")
def generate_episode(body: GenerateRequest) -> dict:
    """Creates episode record and returns JSON immediately; actual generation runs in background."""

    service = EpisodeService()

    # Check if there's already a generating episode for the same date
    existing_episode_id = service.get_generating_episode(body.date)
    if existing_episode_id is not None:
        return {
            "episode_id": existing_episode_id,
            "status": "generating",
            "message": f"Reusing existing generation for {body.date}",
        }

    try:
        episode_id = service.create_episode(
            episode_date=body.date, status="generating"
        )
    except sqlite3.IntegrityError:
        # Kept as a safety net for other UNIQUE constraint violations not covered by the pre-check above
        raise HTTPException(
            status_code=409,
            detail=f"Episode for {body.date} is already being generated",
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


class SynthesizeRequest(BaseModel):
    """音声合成リクエスト"""
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech)")


def _stream_synthesize(episode_id: int, body: SynthesizeRequest) -> Generator[bytes, None, None]:
    service = EpisodeService()
    episode = service.get_episode(episode_id)
    if episode is None:
        yield _format_sse("error", _build_error_payload("エピソードが見つかりません"))
        return

    base_dir = os.path.join(DEFAULT_EPISODES_DIR, str(episode_id))
    script_path = os.path.join(base_dir, "script.json")

    if not os.path.isfile(script_path):
        yield _format_sse("error", _build_error_payload("台本ファイルが見つかりません"))
        return

    settings = get_settings()
    TTS_ENGINES = {"voicevox", "aivispeech"}
    tts_engine = body.tts_engine if body.tts_engine in TTS_ENGINES else settings.default_tts_engine
    if tts_engine == "aivispeech":
        tts_base_url = settings.aivispeech_base_url
        tts_speaker_male = settings.aivispeech_speaker_male
        tts_speaker_female = settings.aivispeech_speaker_female
        tts_engine_label = f"AivisSpeech ({settings.aivispeech_base_url})"
    else:
        tts_base_url = settings.voicevox_base_url
        tts_speaker_male = settings.voicevox_speaker_male
        tts_speaker_female = settings.voicevox_speaker_female
        tts_engine_label = f"VOICEVOX ({settings.voicevox_base_url})"

    service.update_episode_status(episode_id, "generating")

    yield _format_sse("progress", _build_progress_payload("synthesize", f"音声を合成しています... ({tts_engine_label})", engine=tts_engine))
    try:
        success_count = synthesize_episode(
            base_dir,
            base_url=tts_base_url,
            speaker_male=tts_speaker_male,
            speaker_female=tts_speaker_female,
        )
    except Exception as exc:
        logger.exception("tts synthesis failed for episode %d", episode_id)
        service.update_episode_status(episode_id, "failed")
        yield _format_sse("error", _build_error_payload(
            f"音声合成に失敗しました。{tts_engine_label} を確認してください。",
            status="tts_error",
        ))
        return

    if success_count <= 0:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse("error", _build_error_payload(
            f"音声合成に失敗しました。{tts_engine_label} を確認してください。",
            status="tts_error",
        ))
        return

    yield _format_sse("progress", _build_progress_payload("build", "音声ファイルを統合しています..."))
    ep_metadata = build_episode(base_dir)
    if not ep_metadata:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse("error", _build_error_payload("音声の統合に失敗しました", status="build_error"))
        return

    service.update_episode_audio_path(episode_id, ep_metadata.get("audio_path") or "")
    service.update_episode_status(episode_id, "completed")

    yield _format_sse(
        "complete",
        _build_progress_payload(
            "complete",
            f"音声が完成しました (id={episode_id}, lines={success_count})",
            status="completed",
            episode_id=episode_id,
            line_count=success_count,
        ),
    )


@router.post("/episodes/{episode_id}/synthesize", summary="既存エピソードの音声を生成する")
def synthesize_episode_audio(episode_id: int, body: SynthesizeRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_synthesize(episode_id, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ── file-based routes for /episodes and /health are mounted in main.py ──
