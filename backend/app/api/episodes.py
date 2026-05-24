"""Episode list / detail / script endpoints."""

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

router = APIRouter()

EPISODES_BASE_DIR = os.environ.get("EPISODES_DIR", "data/episodes")


def _require_episode(episode_id: int) -> dict:
    """エピソードが存在するか確認し、なければ 404 を返す"""
    service = EpisodeService()
    episode = service.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


@router.get("/episodes", summary="エピソード一覧を取得")
def list_episodes() -> list[dict]:
    """登録されているエピソードの一覧を返す"""
    service = EpisodeService()
    items = service.get_episode_list()
    output: list[dict] = []
    for ep in items:
        item_id = ep["id"]
        audio_url = f"/audio/{item_id}/episode.mp3"
        output.append(
            {
                "id": item_id,
                "title": "",
                "date": ep["episode_date"],
                "duration": 0.0,
                "audio_url": audio_url,
                "status": ep.get("status", "pending"),
            }
        )

    # title と duration を script/metadata から補完
    for entry in output:
        _enrich_episode(entry)

    return output


@router.get("/episodes/latest", summary="最新エピソードを取得")
def get_latest_episode() -> dict:
    """最新（日付降順で最も新しい）エピソードを返す"""
    service = EpisodeService()
    episode = service.get_latest_episode()
    if episode is None:
        raise HTTPException(
            status_code=404, detail="No episodes found"
        )

    result: dict = {
        "id": episode["id"],
        "title": "",
        "date": episode["episode_date"],
        "duration_seconds": 0.0,
        "status": episode.get("status", "pending"),
        "article_count": 0,
        "audio_url": None,
        "articles": [],
    }

    if episode.get("audio_path"):
        result["audio_url"] = f"/audio/{episode['id']}/{episode['audio_path']}"

    # スクリプト・メディア情報で補完
    _enrich_episode(result)

    # DB に items が存在しない場合は script.json から articles を構築
    db_items = service.get_episode_items(episode["id"])
    if not db_items:
        result["articles"] = _load_articles_from_script(episode["id"])
        result["article_count"] = len(result["articles"])

    return result


@router.get("/episodes/{episode_id}", summary="エピソード詳細を取得")
def get_episode(episode_id: int) -> dict:
    """指定されたエピソードの詳細（台本セクション含む）を返す"""
    episode = _require_episode(episode_id)
    service = EpisodeService()
    items = service.get_episode_items(episode_id)

    result: dict = {
        "id": episode["id"],
        "title": "",
        "date": episode["episode_date"],
        "duration_seconds": 0.0,
        "status": episode.get("status", "pending"),
        "article_count": len(items),
        "audio_url": None,
        "articles": items,
    }

    if episode.get("audio_path"):
        result["audio_url"] = f"/audio/{episode['id']}/{episode['audio_path']}"

    _enrich_episode(result)
    return result


@router.get("/episodes/{episode_id}/script", summary="エピソードの台本JSONを取得")
def get_episode_script(episode_id: int) -> dict:
    """script.json に基づく台本データを返す"""
    _require_episode(episode_id)
    script_path = os.path.join(EPISODES_BASE_DIR, str(episode_id), "script.json")

    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail="Script file not found")

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    return script


def _enrich_episode(episode: dict) -> None:
    """script.json または metadata.json からtitle/durationを補完"""
    script_data = os.path.join(
        EPISODES_BASE_DIR, str(episode["id"]), "script.json"
    )
    if os.path.isfile(script_data):
        with open(script_data, "r", encoding="utf-8") as f:
            data = json.load(f)
        episode["title"] = data.get("title", "")

    metadata_data = os.path.join(
        EPISODES_BASE_DIR, str(episode["id"]), "metadata.json"
    )
    if os.path.isfile(metadata_data):
        with open(metadata_data, "r", encoding="utf-8") as f:
            data = json.load(f)
        episode["duration_seconds"] = data.get("duration_seconds", 0.0)


@router.get("/articles/{article_id}", summary="記事詳細を取得")
def get_article(article_id: int) -> dict:
    """指定された記事のタイトル・URL・ソースを返す"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, title, source, url FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return dict(row)


def _load_articles_from_script(episode_id: int) -> list[dict]:
    """DB に items が存在しない場合に script.json から articles を構築して返す"""
    script_path = os.path.join(EPISODES_BASE_DIR, str(episode_id), "script.json")
    if not os.path.isfile(script_path):
        return []

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    articles: list[dict] = []
    for idx, line in enumerate(script.get("lines", []), start=1):
        articles.append({
            "id": idx,
            "article_id": line.get("article_id"),
            "speaker": line.get("speaker"),
            "text": line.get("text", ""),
            "section": line.get("section", "news"),
            "display_text": line.get("display_text"),
            "spoken_text": line.get("spoken_text"),
        })
    return articles
