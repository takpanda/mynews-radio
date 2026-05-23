"""Broadcast generation endpoint (POST /generate)."""

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.batch.generate_script import generate_script
from app.batch.synthesize_voicevox import synthesize_episode
from app.batch.build_episode import build_episode
from app.config import get_settings
from app.services.episode_service import EpisodeService
from app.services.voicevox_client import VoicevoxClient

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")


def _enrich_with_script_data(episode_id: int, base_path: str) -> tuple[str, float]:
    """script.json と metadata.json から番組タイトルと再生時間を取得する。"""
    script_path = os.path.join(base_path, str(episode_id), "script.json")
    title = ""
    if os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", "")

    duration = 0.0
    metadata_path = os.path.join(base_path, str(episode_id), "metadata.json")
    if os.path.isfile(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        duration = data.get("duration_seconds", 0.0)

    return title, duration


class GenerateRequest(BaseModel):
    """番組生成リクエスト"""
    date: str = Field(description="放送日 (YYYY-MM-DD)")
    max_articles: int = Field(default=10, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=640)


class GenerateResponse(BaseModel):
    """番組生成レスポンス"""
    episode_id: int
    status: str
    message: str


@router.post("/generate", response_model=GenerateResponse, summary="番組を生成する")
def generate_episode(body: GenerateRequest) -> dict:
    """日付および記事数指定で番組を同期生成する。

    MVPでは同期実行（生成完了まで待つ）。
    """
    episode_date = body.date
    base_dir = os.path.join(DEFAULT_EPISODES_DIR, episode_date)
    Path(base_dir).mkdir(parents=True, exist_ok=True)

    # Script generation に max_articles を伝える（env経由でbatch関数に渡す）
    old_max = os.environ.get("MAX_SCRIPT_ARTICLES")
    os.environ["MAX_SCRIPT_ARTICLES"] = str(body.max_articles)

    script_path = os.path.join(base_dir, "script.json")
    line_count = generate_script(script_path)
    if old_max is None:
        os.environ.pop("MAX_SCRIPT_ARTICLES", None)
    else:
        os.environ["MAX_SCRIPT_ARTICLES"] = old_max

    if line_count <= 0:
        return GenerateResponse(
            episode_id=0,
            status="no_content",
            message="台本を生成する記事がありません。status='summarized'の記事を登録してください。",
        ).model_dump()

    # 音声合成（VOICEVOX）
    settings = get_settings()
    with VoicevoxClient(
        settings.voicevox_base_url,
        speaker_male=settings.voicevox_speaker_male,
        speaker_female=settings.voicevox_speaker_female,
    ) as client:
        success_count = synthesize_episode(base_dir)

    if success_count <= 0:
        return GenerateResponse(
            episode_id=0,
            status="voicevox_error",
            message=f"音声合成に失敗しました。VOICEVOXエンジン ({settings.voicevox_base_url}) を確認してください。",
        ).model_dump()

    # エピソード統合（WAV結合 + MP3エンコード + metadata.json）
    ep_metadata = build_episode(base_dir)
    if not ep_metadata:
        raise HTTPException(
            status_code=500, detail="番組生成完了したがメタデータ取得に失敗しました"
        )

    # DB登録（episodes + episode_items）
    service = EpisodeService()
    episode_id = service.create_episode(
        episode_date=episode_date,
        script_text=json.dumps(ep_metadata.get("title", ""), ensure_ascii=False),
        audio_path=ep_metadata.get("audio_path"),
        status="completed",
    )

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

    return GenerateResponse(
        episode_id=episode_id,
        status="completed",
        message=f"Episode generated (id={episode_id}, lines={success_count})",
    ).model_dump()


# ── file-based routes for /episodes and /health are mounted in main.py ──
