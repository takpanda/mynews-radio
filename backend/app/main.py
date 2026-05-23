import os
import mimetypes
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.api.episodes import router as episodes_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
settings = get_settings()
app = FastAPI(title="MyNews Radio API", version="0.1.0")

# CORS – Frontend (Next.js on port 3000) from the config value
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# -- Mount sub-routers (order matters for route matching) --

app.include_router(episodes_router)
app.include_router(generate_router)
app.include_router(health_router)


# -- Audio file serving --

EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")


def _locate_audio_file(episode_path: str) -> str:
    """音声ファイルのパスを特定のディレクトリから探す。"""
    episode_dir = os.path.join(EPISODES_DIR, episode_path)

    # metadata.json から audio_path を探す（デフォルト: episode.mp3）
    meta_path = os.path.join(episode_dir, "metadata.json")
    if os.path.isfile(meta_path):
        import json

        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        audio_rel = meta.get("audio_path", "episode.mp3")
        candidate = os.path.join(episode_dir, audio_rel)
        if os.path.isfile(candidate):
            return candidate

    # 直接ファイルの存在を確認（互換性向け）
    for candidate in ["episode.mp3", "episode.wav"]:
        path = os.path.join(episode_dir, candidate)
        if os.path.isfile(path):
            return path

    raise FileNotFoundError("Audio file not found")


@app.get("/audio/{episode_path:path}")
def serve_audio_file(episode_path: str) -> FileResponse:
    """/audio/<episode_id> または /audio/<episode_id>/<filename> で
    音声ファイルをストリーミング配信する。"""

    # episode_path が "episode_id/filename" の2パート構成の場合は分割
    parts = episode_path.split("/")
    if len(parts) >= 2:
        dir_name, filename = parts[0], "/".join(parts[1:])
        candidate = os.path.join(EPISODES_DIR, dir_name, filename)
        if os.path.isfile(candidate):
            media_type, _ = mimetypes.guess_type(candidate)
            media_type = media_type or "application/octet-stream"
            return FileResponse(candidate, media_type=media_type)

    # 1パート（ディレクトリのみ）の場合: metadata.json から音声を探す
    episode_dir_name = parts[0] if parts else ""
    try:
        audio_path = _locate_audio_file(episode_dir_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Audio file not found")

    media_type, _ = mimetypes.guess_type(audio_path)
    media_type = media_type or "application/octet-stream"
    return FileResponse(audio_path, media_type=media_type)
