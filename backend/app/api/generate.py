"""Broadcast generation endpoint (POST /generate)."""

import json
import logging
import os
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.batch.generate_script import generate_script
from app.batch.review_script import review_script
from app.batch.import_articles import import_articles_by_source
from app.batch.summarize_articles import summarize_articles
from app.batch.synthesize_voicevox import synthesize_episode
from app.batch.build_episode import build_episode
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


NEWS_SOURCES = {"hatena_bookmark", "hatena_hotentry_all", "yahoo_news"}


class GenerateRequest(BaseModel):
    """番組生成リクエスト"""
    date: str = Field(description="放送日 (YYYY-MM-DD)")
    max_articles: int = Field(default=10, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)
    news_source: str = Field(default="hatena_bookmark", description="ニュースソース (hatena_bookmark | hatena_hotentry_all | yahoo_news)")
    tts_engine: str = Field(default="aivispeech", description="TTSエンジン (voicevox | aivispeech)")
    enable_review: bool = Field(default=True, description="レビューステップを有効にする")


class GenerateResponse(BaseModel):
    """番組生成レスポンス"""
    episode_id: int
    status: str
    message: str


def _stream_generate(body: GenerateRequest) -> Generator[bytes, None, None]:
    episode_date = body.date
    logger.info("UI generate request: date=%s max_articles=%d", episode_date, body.max_articles)
    service = EpisodeService()
    episode_id = service.create_episode(
        episode_date=episode_date,
        status="generating",
    )
    base_dir = os.path.join(DEFAULT_EPISODES_DIR, str(episode_id))
    Path(base_dir).mkdir(parents=True, exist_ok=True)

    news_source = body.news_source if body.news_source in NEWS_SOURCES else "hatena_bookmark"
    program_name = "テックニュース" if news_source == "hatena_bookmark" else "ニュースのとなり"

    yield _format_sse("progress", _build_progress_payload("start", "エピソード生成を開始します。"))

    # 一般ニュース選択時はRSSから記事をインポートして要約する
    if news_source in {"hatena_hotentry_all", "yahoo_news"}:
        yield _format_sse("progress", _build_progress_payload("import", "一般ニュース記事を取得しています..."))
        try:
            ins, dup = import_articles_by_source(news_source)
            logger.info("RSS import done: inserted=%d duplicated=%d", ins, dup)
        except Exception as exc:
            logger.exception("RSS import failed")
            service.update_episode_status(episode_id, "failed")
            yield _format_sse("error", _build_error_payload(f"記事の取得に失敗しました: {exc}"))
            return

        if ins == 0 and dup == 0:
            service.update_episode_status(episode_id, "failed")
            yield _format_sse("error", _build_error_payload("RSSから記事を取得できませんでした。", status="no_content"))
            return

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

    old_max = os.environ.get("MAX_SCRIPT_ARTICLES")
    os.environ["MAX_SCRIPT_ARTICLES"] = str(body.max_articles)

    try:
        yield _format_sse("progress", _build_progress_payload("generate_script", "台本を生成しています..."))
        script_path = os.path.join(base_dir, "script.json")
        line_count = generate_script(script_path, program_name=program_name, news_source=news_source)
    finally:
        if old_max is None:
            os.environ.pop("MAX_SCRIPT_ARTICLES", None)
        else:
            os.environ["MAX_SCRIPT_ARTICLES"] = old_max

    if line_count <= 0:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse(
            "error",
            _build_error_payload(
                "台本を生成する記事がありません。status='summarized'の記事を登録してください。",
                status="no_content",
            ),
        )
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

    reviewed_episode_id: int | None = None
    reviewed_episode_dir: str | None = None
    review_result: dict = {"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0}

    if body.enable_review:
        yield _format_sse("progress", _build_progress_payload("review", "4人のディレクターが台本をレビューしています..."))
        try:
            reviewed_episode_id = service.create_episode(episode_date=episode_date, status="generating")
            reviewed_episode_dir = os.path.join(DEFAULT_EPISODES_DIR, str(reviewed_episode_id))
            Path(reviewed_episode_dir).mkdir(parents=True, exist_ok=True)
            Path(os.path.join(reviewed_episode_dir, "lines")).mkdir(exist_ok=True)
            review_result = review_script(script_path, reviewed_episode_dir)
            logger.info(
                "review_script: revised=%s review_count=%d",
                review_result["revised"],
                review_result["review_count"],
            )
            review_msg = f"レビュー完了（{review_result['review_count']}人のディレクター）"
            if review_result.get("revised"):
                review_msg += " — 台本を修正しました"
            yield _format_sse("progress", _build_progress_payload("review_done", review_msg, status="completed"))
        except Exception as exc:
            logger.warning("review_script failed (non-fatal): %s", exc)
            if reviewed_episode_id is not None:
                service.update_episode_status(reviewed_episode_id, "failed")
            yield _format_sse("progress", _build_progress_payload("review_done", "レビューをスキップしました（エラー）", status="skipped"))

    yield _format_sse("progress", _build_progress_payload("synthesize", f"音声を合成しています... ({tts_engine_label})", engine=tts_engine))
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
        yield _format_sse(
            "error",
            _build_error_payload(
                f"音声合成に失敗しました。{tts_engine_label} を確認してください。",
                status="tts_error",
            ),
        )
        return

    if success_count <= 0:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse(
            "error",
            _build_error_payload(
                f"音声合成に失敗しました。{tts_engine_label} を確認してください。",
                status="tts_error",
            ),
        )
        return

    yield _format_sse("progress", _build_progress_payload("build", "音声ファイルを統合しています..."))
    ep_metadata = build_episode(base_dir)
    if not ep_metadata:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse(
            "error",
            _build_error_payload(
                "番組生成完了したがメタデータ取得に失敗しました",
                status="build_error",
            ),
        )
        return

    service.update_episode_audio_path(episode_id, ep_metadata.get("audio_path") or "")
    service.update_episode_status(episode_id, "completed")

    yield _format_sse("progress", _build_progress_payload("db", "エピソードを保存しています...", status="completed"))
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
        logger.exception("failed to persist episode items")

    # Build reviewed episode (non-fatal)
    if reviewed_episode_id is not None and reviewed_episode_dir is not None:
        if review_result.get("revised"):
            try:
                yield _format_sse("progress", _build_progress_payload("review_synthesize", "レビュー版を音声合成しています..."))
                reviewed_wav = synthesize_episode(
                    reviewed_episode_dir,
                    base_url=tts_base_url,
                    speaker_male=tts_speaker_male,
                    speaker_female=tts_speaker_female,
                )
                if reviewed_wav <= 0:
                    raise RuntimeError("reviewed synthesize produced 0 WAV files")

                yield _format_sse("progress", _build_progress_payload("review_build", "レビュー版を統合しています..."))
                reviewed_meta = build_episode(reviewed_episode_dir)
                if not reviewed_meta:
                    raise RuntimeError("reviewed build_episode returned empty metadata")

                service.update_episode_audio_path(reviewed_episode_id, reviewed_meta.get("audio_path") or "")
                service.update_episode_status(reviewed_episode_id, "completed")
                yield _format_sse(
                    "progress",
                    _build_progress_payload(
                        "review_complete",
                        f"レビュー版が完成しました（id={reviewed_episode_id}）",
                        status="completed",
                    ),
                )
            except Exception as exc:
                logger.warning("Reviewed episode build failed (non-fatal): %s", exc)
                service.update_episode_status(reviewed_episode_id, "failed")
        else:
            service.update_episode_status(reviewed_episode_id, "failed")

    yield _format_sse(
        "complete",
        _build_progress_payload(
            "complete",
            f"Episode generated (id={episode_id}, lines={success_count})",
            status="completed",
            episode_id=episode_id,
            line_count=success_count,
        ),
    )


@router.post("/generate", summary="番組を生成する")
def generate_episode(body: GenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_generate(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ── file-based routes for /episodes and /health are mounted in main.py ──
