"""Episode list / detail / script endpoints."""

import json
import os
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, Query

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

router = APIRouter()

def _episodes_base_dir() -> str:
    return os.environ.get("EPISODES_DIR", "data/episodes")


def _require_episode(episode_id: int) -> dict:
    """エピソードが存在するか確認し、なければ 404 を返す"""
    service = EpisodeService()
    episode = service.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


def _resolve_episode_directory(episode: dict) -> str:
    base = _episodes_base_dir()
    id_dir = os.path.join(base, str(episode.get("id", "")))
    if os.path.isdir(id_dir):
        return id_dir

    episode_date = episode.get("episode_date") or episode.get("date") or ""
    date_dir = os.path.join(base, episode_date)
    if os.path.isdir(date_dir):
        return date_dir

    return id_dir


def _build_audio_url(episode: dict) -> Optional[str]:
    audio_path = episode.get("audio_path")
    if not audio_path:
        return None

    base_dir = _resolve_episode_directory(episode)
    if not os.path.isdir(base_dir):
        return None

    dir_name = os.path.basename(base_dir)
    if not dir_name:
        return None

    return f"/audio/{dir_name}/{audio_path}"


@router.get("/episodes", summary="エピソード一覧を取得")
def list_episodes(
    limit: Optional[int] = Query(None, ge=1, description="取得件数"),
    offset: int = Query(0, ge=0, description="取得開始位置"),
) -> Union[list[dict], dict]:
    """登録されているエピソードの一覧を返す。

    limit を指定しない場合は全件返却（従来動作）。
    limit を指定した場合はページネーション情報を含む辞書を返す。
    """
    service = EpisodeService()
    items = service.get_episode_list(limit=limit, offset=offset)
    output: list[dict] = []
    for ep in items:
        output.append(
            {
                "id": ep["id"],
                "title": "",
                "subtitle": "",
                "date": ep["episode_date"],
                "duration": 0.0,
                "audio_url": None,
                "status": ep.get("status", "pending"),
                "audio_path": ep.get("audio_path"),
                "type": ep.get("type", "radio"),
                "source_url": ep.get("source_url"),
            }
        )

    # title と duration を script/metadata から補完
    for entry in output:
        audio = _build_audio_url(entry)
        if audio:
            entry["audio_url"] = audio
        _enrich_episode(entry)

    for entry in output:
        entry.pop("audio_path", None)
        entry.setdefault("has_script", False)

    if limit is not None:
        total = service.count_episodes()
        return {
            "items": output,
            "total": total,
            "has_next": (offset + limit) < total,
        }

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
        "subtitle": "",
        "date": episode["episode_date"],
        "duration_seconds": 0.0,
        "status": episode.get("status", "pending"),
        "type": episode.get("type", "radio"),
        "source_url": episode.get("source_url"),
        "article_count": 0,
        "audio_url": None,
        "articles": [],
    }

    if episode.get("audio_path"):
        result["audio_url"] = _build_audio_url(episode)

    # スクリプト・メディア情報で補完
    _enrich_episode(result)

    # DB に items が存在する場合はそのまま articles に設定、なければ script.json から構築
    db_items = service.get_episode_items(episode["id"])
    if db_items:
        result["articles"] = db_items
        result["article_count"] = len(db_items)
    else:
        result["articles"] = _load_articles_from_script(episode)
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
        "subtitle": "",
        "date": episode["episode_date"],
        "duration_seconds": 0.0,
        "status": episode.get("status", "pending"),
        "type": episode.get("type", "radio"),
        "source_url": episode.get("source_url"),
        "phase": episode.get("phase", ""),
        "generation_phase": episode.get("phase", ""),
        "generation_message": episode.get("generation_message", ""),
        "article_count": len(items),
        "audio_url": None,
        "articles": items,
    }

    if episode.get("audio_path"):
        result["audio_url"] = _build_audio_url(episode)

    _enrich_episode(result)
    return result


@router.get("/episodes/{episode_id}/script", summary="エピソードの台本JSONを取得")
def get_episode_script(episode_id: int) -> dict:
    """script.json の内容に DB のエピソード情報を付与して返す"""
    episode = _require_episode(episode_id)
    base_dir = _resolve_episode_directory(episode)
    script_path = os.path.join(base_dir, "script.json")

    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail="Script file not found")

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    return {
        "id": episode["id"],
        "episode_date": episode["episode_date"],
        "title": script.get("title", ""),
        "subtitle": script.get("subtitle", ""),
        "lines": script.get("lines", []),
        "generated_at": episode.get("updated_at", ""),
    }


@router.get("/episodes/{episode_id}/review", summary="エピソードのレビュー結果JSONを取得")
def get_episode_review(episode_id: int) -> dict:
    """review.json の内容をそのまま返す"""
    episode = _require_episode(episode_id)
    base_dir = _resolve_episode_directory(episode)

    new_path = os.path.join(base_dir, "review", "review.json")
    old_path = os.path.join(base_dir, "review.json")

    if os.path.isfile(new_path):
        review_path = new_path
    elif os.path.isfile(old_path):
        review_path = old_path
    else:
        raise HTTPException(status_code=404, detail="Review file not found")

    with open(review_path, "r", encoding="utf-8") as f:
        review = json.load(f)

    return review


def _enrich_episode(episode: dict) -> None:
    """script.json または metadata.json からtitle/subtitle/durationを補完"""
    base_dir = _resolve_episode_directory(episode)
    script_data = os.path.join(base_dir, "script.json")
    if os.path.isfile(script_data):
        with open(script_data, "r", encoding="utf-8") as f:
            data = json.load(f)
        episode["title"] = data.get("title", "")
        episode["subtitle"] = data.get("subtitle", "")
        episode["has_script"] = True

    metadata_data = os.path.join(base_dir, "metadata.json")
    if os.path.isfile(metadata_data):
        with open(metadata_data, "r", encoding="utf-8") as f:
            data = json.load(f)
        duration = data.get("duration_seconds", 0.0)
        episode["duration_seconds"] = duration
        if "duration" in episode:
            episode["duration"] = duration


@router.get("/articles/{article_id}", summary="記事詳細を取得")
def get_article(article_id: int) -> dict:
    """指定された記事のタイトル・URL・ソース・要約を返す"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, title, source, url, summary FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return dict(row)


def _load_articles_from_script(episode: dict) -> list[dict]:
    """DB に items が存在しない場合に script.json から articles を構築して返す"""
    base_dir = _resolve_episode_directory(episode)
    script_path = os.path.join(base_dir, "script.json")
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
