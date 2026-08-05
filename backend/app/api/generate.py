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
from app.audit import finalize_audit_log
from app.auth import require_owner_session
from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.article_service import ArticleService
from app.services.episode_service import EpisodeService
from app.services.hatena_fetcher import _validate_url_public, fetch_article_by_url
from app.services.settings_service import get_settings_or_default, validate_settings
from app.services.generation_control import GenerationControlError, bind_episode, claim_job, finish_job
from app.services.verified_client_ip import get_verified_client_ip
from app.services.llm_provider import validate_provider_model

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_generate_rate_limit() -> str:
    return get_settings().generate_rate_limit


def _rate_limit_key(request: Request) -> str:
    """管理セッション単位で制限し、共有プロキシIPで利用者を束ねない。"""
    token = request.cookies.get("admin_session")
    return f"session:{token}" if token else get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


def _client_ip(request: Request) -> str:
    return get_verified_client_ip(request)


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
    max_articles: int | None = Field(default=None, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)
    news_source: str = Field(default="hatena_bookmark", description="ニュースソース (hatena_bookmark | hatena_hotentry_all | yahoo_news)")
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech | fishs2pro)")
    url: str | None = Field(default=None, description="解説対象の記事URL（指定時はnews_sourceは無視）")
    style: str = Field(default="solo", description="解説スタイル (solo | dialogue)")
    mc_gender: str = Field(default="male", description="MC性別 (male | female)")
    settings_snapshot: dict[str, Any] | None = Field(default=None, description="生成開始時に適用する番組設定")
    llm_provider: str | None = Field(default=None, description="LLMプロバイダー")
    llm_model: str | None = Field(default=None, description="LLMモデル")


def _run_generation(episode_id: int, body: GenerateRequest) -> None:
    """Background pipeline that delegates to the shared radio pipeline."""

    service = EpisodeService()
    ep = service.get_episode(episode_id)
    seq = ep.get("seq", 0) if ep else 0

    news_source = body.news_source if body.news_source in {"hatena_bookmark", "hatena_hotentry_all", "yahoo_news"} else "hatena_bookmark"
    llm = validate_provider_model(body.llm_provider, body.llm_model)

    logger.info("Background generation started: episode_id=%d date=%s seq=%d", episode_id, body.date, seq)

    def _progress(phase: str, message: str) -> None:
        service.update_episode_phase(episode_id, phase, message)

    result = run_radio_pipeline(
        episode_id,
        episode_date=body.date,
        news_source=news_source,
        seq=seq,
        max_articles=body.max_articles,
        program_settings=(
            validate_settings(**body.settings_snapshot)
            if body.settings_snapshot is not None
            else get_settings_or_default()
        ),
        tts_engine=body.tts_engine,
        default_episodes_dir=DEFAULT_EPISODES_DIR,
        progress_callback=_progress,
        llm_provider=llm.name,
        llm_model=llm.model,
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
        llm = validate_provider_model(body.llm_provider, body.llm_model)
        line_count = generate_commentary_script(script_path, article, style=style, mc_gender=mc_gender,
                                                llm_provider=llm.name, llm_model=llm.model)

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
            review_result = review_script(script_path, reviewed_episode_dir,
                                          llm_provider=llm.name, llm_model=llm.model)
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
        tts_engines = {"voicevox", "aivispeech", "fishs2pro"}
        tts_engine = body.tts_engine if body.tts_engine in tts_engines else settings.default_tts_engine
        if tts_engine == "fishs2pro":
            tts_base_url = settings.fishs2pro_base_url
            tts_speaker_male = None
            tts_speaker_female = None
        elif tts_engine == "aivispeech":
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
                tts_engine=tts_engine,
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

        service.complete_radio_episode_with_notification(episode_id)
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


@router.post("/generate", summary="番組を生成する（バックグラウンド実行）")
@limiter.limit(_get_generate_rate_limit)
def generate_episode(request: Request, body: GenerateRequest, owner_user_id: int = Depends(require_owner_session)) -> dict:
    """Creates episode record and returns JSON immediately; actual generation runs in background."""

    # Validate: mc_gender
    if body.mc_gender not in VALID_GENDERS:
        raise HTTPException(status_code=400, detail="mc_gender must be 'male' or 'female'")

    if body.settings_snapshot is not None:
        try:
            validate_settings(**body.settings_snapshot)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid settings_snapshot: {exc}") from exc

    try:
        validate_provider_model(body.llm_provider, body.llm_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid llm selection: {exc}") from exc

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

    idempotency_key = request.headers.get("Idempotency-Key")
    operation = "commentary" if body.url else "generate"
    try:
        claim = claim_job(
            owner_user_id, operation, idempotency_key or "",
            ({k: v for k, v in (body.model_dump() if hasattr(body, "model_dump") else body.dict()).items()
              if not (k in {"llm_provider", "llm_model"} and v is None)}),
            episode_date=body.date, episode_type=episode_type, source_url=body.url,
            client_ip=_client_ip(request),
        )
    except GenerationControlError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    if claim.duplicate:
        episode = EpisodeService().get_episode(claim.episode_id) if claim.episode_id else None
        return {"episode_id": claim.episode_id, "status": (episode or {}).get("status", "generating"), "message": "Existing generation job returned"}

    episode_id = claim.episode_id
    if episode_id is None:
        finish_job(claim.job_id, False)
        raise HTTPException(status_code=503, detail="Generation reservation failed")
    service = EpisodeService()
    logger.info("Episode record created: id=%d, date=%s", episode_id, body.date)
    service.update_episode_phase(
        episode_id, "start",
        "解説の生成を準備しています…" if episode_type == "commentary" else "番組の生成を準備しています…",
    )

    bind_episode(claim.job_id, episode_id)
    # Start actual pipeline in background; prefer asyncio under uvicorn
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    pipeline = _run_commentary_generation if episode_type == "commentary" else _run_generation

    if loop is not None:
        asyncio.ensure_future(_async_wrapper(episode_id, body, pipeline, owner_user_id, operation, claim.job_id))
    else:
        import threading as _th
        t = _th.Thread(target=_run_pipeline_with_audit, args=(episode_id, body, pipeline, owner_user_id, operation, claim.job_id), daemon=True)
        t.start()

    msg = f"Commentary generation started for {body.url}" if episode_type == "commentary" else f"Episode generation started for {body.date}"
    return {
        "episode_id": episode_id,
        "status": "generating",
        "message": msg,
    }


def _run_pipeline_with_audit(episode_id: int, body: GenerateRequest, pipeline: callable, owner_user_id: int, operation: str, job_id: int) -> None:
    try:
        pipeline(episode_id, body)
    except Exception:
        logger.exception("generation pipeline failed for episode %d", episode_id)
    finally:
        status = (EpisodeService().get_episode(episode_id) or {}).get("status")
        success = status == "completed"
        try:
            finalize_audit_log(job_id, "success" if success else "failure", episode_id)
        except Exception:
            # 終了監査が失敗してもジョブをactiveのまま残さず、再実行可能な失敗へ遷移させる。
            logger.exception("failed to finalize audit log for generation job %d", job_id)
            success = False
        finally:
            finish_job(job_id, success)


async def _async_wrapper(episode_id: int, body: GenerateRequest, pipeline: callable = _run_generation, owner_user_id: int | None = None, operation: str = "generate", job_id: int = 0) -> None:
    """Run synchronous pipeline in a thread to not block the event loop."""
    await asyncio.to_thread(_run_pipeline_with_audit, episode_id, body, pipeline, owner_user_id, operation, job_id)


class SynthesizeRequest(BaseModel):
    """音声合成リクエスト"""
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech | fishs2pro)")


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
    TTS_ENGINES = {"voicevox", "aivispeech", "fishs2pro"}
    tts_engine = body.tts_engine if body.tts_engine in TTS_ENGINES else settings.default_tts_engine
    if tts_engine == "fishs2pro":
        tts_base_url = settings.fishs2pro_base_url
        tts_speaker_male = None
        tts_speaker_female = None
        tts_engine_label = "Fish S2 Pro"
    elif tts_engine == "aivispeech":
        tts_base_url = settings.aivispeech_base_url
        tts_speaker_male = settings.aivispeech_speaker_male
        tts_speaker_female = settings.aivispeech_speaker_female
        tts_engine_label = "AivisSpeech"
    else:
        tts_base_url = settings.voicevox_base_url
        tts_speaker_male = settings.voicevox_speaker_male
        tts_speaker_female = settings.voicevox_speaker_female
        tts_engine_label = "VOICEVOX"

    service.update_episode_status(episode_id, "generating")

    yield _format_sse("progress", _build_progress_payload("synthesize", f"音声を合成しています... ({tts_engine_label})", engine=tts_engine))
    try:
        success_count = synthesize_episode(
            base_dir,
            base_url=tts_base_url,
            speaker_male=tts_speaker_male,
            speaker_female=tts_speaker_female,
            tts_engine=tts_engine,
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
    service.complete_radio_episode_with_notification(episode_id)

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
@limiter.limit(_get_generate_rate_limit)
def synthesize_episode_audio(episode_id: int, request: Request, body: SynthesizeRequest, owner_user_id: int = Depends(require_owner_session)) -> StreamingResponse:
    episode = EpisodeService().get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    idempotency_key = request.headers.get("Idempotency-Key")
    try:
        claim = claim_job(
            owner_user_id, "synthesize", idempotency_key or "",
            {"episode_id": episode_id, "body": body.model_dump() if hasattr(body, "model_dump") else body.dict()},
            episode_id=episode_id,
            client_ip=_client_ip(request),
        )
    except GenerationControlError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    if claim.duplicate:
        if claim.status == "active":
            event = "progress"
            payload = _build_progress_payload(
                "synthesize", "Existing synthesis job is still running", status="running", episode_id=episode_id,
                reused=True,
            )
        elif claim.status == "completed":
            event = "complete"
            payload = _build_progress_payload(
                "complete", "Existing synthesis job returned", status="completed", episode_id=episode_id
            )
        else:
            event = "error"
            payload = _build_error_payload("Existing synthesis job failed", status="failed")
            payload["episode_id"] = episode_id
        return StreamingResponse(iter([_format_sse(event, payload)]), media_type="text/event-stream")
    return StreamingResponse(
        _stream_synthesize_with_audit(episode_id, body, owner_user_id, claim.job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _finalize_synthesis_job(job_id: int, episode_id: int) -> None:
    """Close the job before emitting a terminal SSE event.

    A client can disconnect as soon as it receives ``complete`` or ``error``.
    Keeping the completion update in the generator's finalizer would then leave
    it suspended before the next iteration.
    """
    status = (EpisodeService().get_episode(episode_id) or {}).get("status")
    success = status == "completed"
    try:
        finalize_audit_log(job_id, "success" if success else "failure", episode_id)
    except Exception:
        logger.exception("failed to finalize audit log for synthesis job %d", job_id)
        success = False

    try:
        finish_job(job_id, success)
    except Exception:
        # This makes an attempted completion distinguishable from a process
        # exit before this point.  Do not include request or credential data.
        logger.exception("failed to finish synthesis job %d; it may remain active", job_id)
        raise

    logger.info("synthesis job finalized: job_id=%d success=%s", job_id, success)


def _is_terminal_synthesis_event(payload: bytes) -> bool:
    return payload.startswith(b"event: complete\n") or payload.startswith(b"event: error\n")


def _stream_synthesize_with_audit(episode_id: int, body: SynthesizeRequest, owner_user_id: int, job_id: int) -> Generator[bytes, None, None]:
    finalized = False
    try:
        for payload in _stream_synthesize(episode_id, body):
            # The terminal SSE must be the last thing sent.  In particular the
            # UI returns from its reader as soon as it receives this event.
            if _is_terminal_synthesis_event(payload):
                finalized = True
                _finalize_synthesis_job(job_id, episode_id)
            yield payload
    finally:
        if not finalized:
            _finalize_synthesis_job(job_id, episode_id)


# ── file-based routes for /episodes and /health are mounted in main.py ──
