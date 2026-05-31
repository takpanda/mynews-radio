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
from app.batch.import_articles import import_articles_by_source
from app.batch.summarize_articles import summarize_articles
from app.batch.synthesize_voicevox import synthesize_episode
from app.batch.build_episode import build_episode
from app.config import get_settings
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")


def _format_sse(event: str, payload: dict) -> bytes:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


def _build_error_payload(message: str, status: str = "error") -> dict:
    return {"phase": "failed", "status": status, "message": message}


NEWS_SOURCES = {"hatena_bookmark", "hatena_hotentry_all"}


class GenerateRequest(BaseModel):
    """番組生成リクエスト"""
    date: str = Field(description="放送日 (YYYY-MM-DD)")
    max_articles: int = Field(default=10, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)
    news_source: str = Field(default="hatena_bookmark", description="ニュースソース (hatena_bookmark | hatena_hotentry_all)")
    tts_engine: str = Field(default="voicevox", description="TTSエンジン (voicevox | aivispeech)")


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

    yield _format_sse("progress", {"phase": "start", "message": "エピソード生成を開始します。"})

    # 一般ニュース選択時はRSSから記事をインポートして要約する
    if news_source == "hatena_hotentry_all":
        yield _format_sse("progress", {"phase": "import", "message": "一般ニュース記事を取得しています..."})
        try:
            ins, dup = import_articles_by_source("hatena_hotentry_all")
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

        yield _format_sse("progress", {"phase": "summarize", "message": "記事を要約しています..."})
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
        yield _format_sse("progress", {"phase": "generate_script", "message": "台本を生成しています..."})
        script_path = os.path.join(base_dir, "script.json")
        line_count = generate_script(script_path)
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
    tts_engine = body.tts_engine if body.tts_engine in TTS_ENGINES else "voicevox"
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

    yield _format_sse("progress", {"phase": "synthesize", "message": f"音声を合成しています... ({tts_engine_label})"})
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
                status="voicevox_error",
            ),
        )
        return

    if success_count <= 0:
        service.update_episode_status(episode_id, "failed")
        yield _format_sse(
            "error",
            _build_error_payload(
                f"音声合成に失敗しました。{tts_engine_label} を確認してください。",
                status="voicevox_error",
            ),
        )
        return

    yield _format_sse("progress", {"phase": "build", "message": "音声ファイルを統合しています..."})
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

    yield _format_sse("progress", {"phase": "db", "message": "エピソードを保存しています..."})
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

    yield _format_sse(
        "complete",
        {
            "phase": "complete",
            "episode_id": episode_id,
            "status": "completed",
            "message": f"Episode generated (id={episode_id}, lines={success_count})",
        },
    )


@router.post("/generate", summary="番組を生成する")
def generate_episode(body: GenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_generate(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ── file-based routes for /episodes and /health are mounted in main.py ──
