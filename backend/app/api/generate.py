"""Broadcast generation endpoint (POST /generate) - async background execution."""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Generator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.batch.generate_commentary_script import generate_commentary_script
from app.batch.radio_pipeline import run_radio_pipeline
from app.batch.synthesize_voicevox import synthesize_episode
from app.batch.build_episode import build_episode
from app.batch.review_script import review_script
from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.article_service import ArticleService
from app.services.episode_service import EpisodeService
from app.services.hatena_fetcher import _validate_url_public, fetch_article_by_url

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_generate_rate_limit() -> str:
    return get_settings().generate_rate_limit


limiter = Limiter(key_func=get_remote_address)


def verify_api_key(authorization: str | None = Header(None)) -> None:
    settings = get_settings()
    if not settings.api_key:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    token = authorization[7:]
    if token != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def require_admin_key(authorization: str | None = Header(None)) -> None:
    settings = get_settings()
    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API requires API_KEY to be configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    token = authorization[7:]
    if token != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")
VALID_GENDERS = {"male", "female"}

PHASE_SEQUENCE = {
    "start": {"step_index": 0, "step_total": 6, "step_label": "開始"},
    "import": {"step_index": 1, "step_total": 6, "step_label": "記事取得"},
    "summarize": {"step_index": 2, "step_total": 6, "step_label": "要約"},
    "generate_script": {"step_index": 3, "step_total": 6, "step_label": "台本生成"},
    "review": {"step_index": 4, "step_total": 6, "step_label": "レビュー"},
    "review_done": {"step_index": 4, "step_total": 6, "step_label": "レビュー"},
    "reviewed": {"step_index": 4, "step_total": 6, "step_label": "レビュー完了"},
    "synthesize": {"step_index": 5, "step_total": 6, "step_label": "音声合成"},
    "build": {"step_index": 6, "step_total": 6, "step_label": "音声統合"},
    "db": {"step_index": 6, "step_total": 6, "step_label": "保存"},
    "review_synthesize": {"step_index": 6, "step_total": 6, "step_label": "レビュー版音声合成"},
    "review_build": {"step_index": 6, "step_total": 6, "step_label": "レビュー版統合"},
    "review_complete": {"step_index": 6, "step_total": 6, "step_label": "レビュー版完了"},
    "complete": {"step_index": 6, "step_total": 6, "step_label": "完了"},
    "failed": {"step_index": 0, "step_total": 6, "step_label": "失敗"},
    # Commentary phases (step_total=6)
    "fetch_article": {"step_index": 1, "step_total": 6, "step_label": "記事取得"},
    "generate_commentary": {"step_index": 2, "step_total": 6, "step_label": "解説生成"},
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
    url: str | None = Field(default=None, description="解説対象の記事URL（指定時はnews_sourceは無視）")
    style: str = Field(default="solo", description="解説スタイル (solo | dialogue)")
    mc_gender: str = Field(default="male", description="MC性別 (male | female)")


def _run_generation(episode_id: int, body: GenerateRequest) -> None:
    """Background pipeline that delegates to the shared radio pipeline."""

    service = EpisodeService()
    ep = service.get_episode(episode_id)
    seq = ep.get("seq", 0) if ep else 0

    news_source = body.news_source if body.news_source in {"hatena_bookmark", "hatena_hotentry_all", "yahoo_news"} else "hatena_bookmark"

    logger.info("Background generation started: episode_id=%d date=%s seq=%d", episode_id, body.date, seq)

    def _progress(phase: str, message: str) -> None:
        service.update_episode_phase(episode_id, phase, message)

    result = run_radio_pipeline(
        episode_id,
        episode_date=body.date,
        news_source=news_source,
        seq=seq,
        max_articles=body.max_articles,
        tts_engine=body.tts_engine,
        default_episodes_dir=DEFAULT_EPISODES_DIR,
        progress_callback=_progress,
    )

    if result is None:
        logger.warning("[%d] radio pipeline returned None", episode_id)


# ---------------------------------------------------------------------------
# Commentary pipeline
# ---------------------------------------------------------------------------

def _run_commentary_generation(episode_id: int, body: GenerateRequest) -> None:
    """Background pipeline for URL-based commentary generation."""
    service: EpisodeService | None = None
    try:
        service = EpisodeService()
        episode_date = body.date
        base_dir = os.path.join(DEFAULT_EPISODES_DIR, str(episode_id))

        Path(base_dir).mkdir(parents=True, exist_ok=True)

        style = body.style if body.style in {"solo", "dialogue"} else "solo"
        mc_gender = body.mc_gender if body.mc_gender in VALID_GENDERS else "male"
        logger.info(
            "Background commentary started: episode_id=%d date=%s url=%s style=%s mc_gender=%s",
            episode_id, episode_date, body.url, style, body.mc_gender,
        )

        # -- START --
        service.update_episode_phase(episode_id, "start", "解説の生成を準備しています…")
        logger.info("[%d] phase=start (commentary)", episode_id)

        # -- FETCH ARTICLE --
        service.update_episode_phase(episode_id, "fetch_article", "記事を取得しています…")
        article = fetch_article_by_url(body.url)
        if not article.get("text"):
            logger.error("Failed to fetch article from URL: %s", body.url)
            service.update_episode_status(episode_id, "failed")
            return

        # Upsert article to DB to get an article_id
        article_svc = ArticleService()
        created = article_svc.upsert_article(article)
        logger.info("Article upserted for URL: created=%s url=%s", created, body.url)

        # Re-fetch to get the article_id
        articles = article_svc.fetch_new_articles()
        article_id = None
        for a in articles:
            if a.get("url") == body.url:
                article_id = a["id"]
                break
        if article_id is None:
            # Fallback: fetch from DB by URL
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM articles WHERE url = ?", (body.url,)
                ).fetchone()
                if row:
                    article_id = row["id"]
        if article_id is None:
            logger.error("Could not resolve article_id for URL: %s", body.url)
            service.update_episode_status(episode_id, "failed")
            return

        article["id"] = article_id

        # -- GENERATE COMMENTARY SCRIPT --
        service.update_episode_phase(episode_id, "generate_commentary", "解説台本を生成しています…")
        script_path = os.path.join(base_dir, "script.json")
        line_count = generate_commentary_script(script_path, article, style=style, mc_gender=mc_gender)

        if line_count <= 0:
            service.update_episode_status(episode_id, "failed")
            return

        review_result: dict[str, Any] = {"revised": False, "review_count": 0}

        # -- REVIEW (quality gate) --
        service.update_episode_phase(episode_id, "review", "台本をレビューしています…")
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
            service.update_episode_phase(episode_id, "review_done", "レビューが完了しました…")
        except Exception as exc:
            logger.warning("review_script failed (non-fatal): %s", exc)

        # -- BRANCH based on revised flag --
        if review_result.get("revised"):
            shutil.copy(os.path.join(reviewed_episode_dir, "script.json"), script_path)

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

        # -- SYNTHESIZE TTS --
        service.update_episode_phase(episode_id, "synthesize", "音声を合成しています…")
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
        service.update_episode_phase(episode_id, "build", "音声をまとめています…")
        ep_metadata = build_episode(base_dir)
        if not ep_metadata:
            service.update_episode_status(episode_id, "failed")
            return

        service.update_episode_audio_path(
            episode_id, ep_metadata.get("audio_path") or ""
        )

        # -- PERSIST ITEMS (before marking completed, so failure keeps episode in failed state) --
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
            return

        service.update_episode_status(episode_id, "completed")
        service.update_episode_phase(episode_id, "complete", "解説の生成が完了しました")
        logger.info("[%d] commentary completed successfully", episode_id)

    except Exception as exc:
        if service is not None:
            current = service.get_episode(episode_id)
            current_status = current["status"] if current else None
            if current_status not in {"completed", "failed"}:
                logger.exception("[%d] commentary generation failed unexpectedly", episode_id)
                service.update_episode_status(episode_id, "failed")
        else:
            logger.exception("[%d] commentary generation failed before service init", episode_id)


@router.post("/generate", summary="番組を生成する（バックグラウンド実行）", dependencies=[Depends(verify_api_key)])
@limiter.limit(_get_generate_rate_limit)
def generate_episode(request: Request, body: GenerateRequest) -> dict:
    """Creates episode record and returns JSON immediately; actual generation runs in background."""

    # Validate: mc_gender
    if body.mc_gender not in VALID_GENDERS:
        raise HTTPException(status_code=400, detail="mc_gender must be 'male' or 'female'")

    # Validate: url 指定時は style をチェック → SSRFチェック
    if body.url:
        if body.style not in {"solo", "dialogue"}:
            raise HTTPException(
                status_code=400,
                detail="style must be 'solo' or 'dialogue'",
            )
        try:
            _validate_url_public(body.url)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Access to internal network address is not allowed",
            )
        episode_type = "commentary"
    else:
        episode_type = "radio"

    service = EpisodeService()

    if episode_type == "radio":
        episode_id, seq = service.create_radio_episode(
            episode_date=body.date, status="generating"
        )
        logger.info("Episode record created: id=%d, date=%s, seq=%d", episode_id, body.date, seq)
        service.update_episode_phase(episode_id, "start", "番組の生成を準備しています…")
    else:
        try:
            episode_id = service.create_episode(
                episode_date=body.date,
                status="generating",
                type="commentary",
                source_url=body.url,
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail=f"Episode for {body.date} already exists",
            )
        service.update_episode_phase(episode_id, "start", "解説の生成を準備しています…")

    # Start actual pipeline in background; prefer asyncio under uvicorn
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    pipeline = _run_commentary_generation if episode_type == "commentary" else _run_generation

    if loop is not None:
        asyncio.ensure_future(_async_wrapper(episode_id, body, pipeline))
    else:
        import threading as _th
        t = _th.Thread(target=pipeline, args=(episode_id, body), daemon=True)
        t.start()

    msg = f"Commentary generation started for {body.url}" if episode_type == "commentary" else f"Episode generation started for {body.date}"
    return {
        "episode_id": episode_id,
        "status": "generating",
        "message": msg,
    }


async def _async_wrapper(episode_id: int, body: GenerateRequest, pipeline: callable = _run_generation) -> None:
    """Run synchronous pipeline in a thread to not block the event loop."""
    await asyncio.to_thread(pipeline, episode_id, body)


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


@router.post("/episodes/{episode_id}/synthesize", summary="既存エピソードの音声を生成する", dependencies=[Depends(verify_api_key)])
@limiter.limit(_get_generate_rate_limit)
def synthesize_episode_audio(episode_id: int, request: Request, body: SynthesizeRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_synthesize(episode_id, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ── file-based routes for /episodes and /health are mounted in main.py ──
