"""MCプロフィール写真の公開配信API。"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db.connection import get_db_connection


router = APIRouter(tags=["mc-photos"])


def _mc_photo_file_path(photo_path: str | None) -> str | None:
    """DB上の写真ファイル名を解決し、配信ディレクトリ外への参照を拒否する。"""
    if not isinstance(photo_path, str) or not photo_path:
        return None

    try:
        photos_dir = os.path.realpath(get_settings().mc_photos_dir)
        candidate = os.path.realpath(os.path.join(photos_dir, photo_path))
    except (OSError, ValueError):
        return None
    if candidate == photos_dir or not candidate.startswith(photos_dir + os.sep):
        return None
    return candidate


@router.get("/mcs/{mc_id}/photo", summary="MCプロフィール写真を取得")
def get_mc_photo(mc_id: str) -> FileResponse:
    """MC写真を公開配信する。MCや写真ファイルが無い場合は404を返す。"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT photo_path FROM mc_profiles WHERE id = ?", (mc_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="MC photo not found")

    file_path = _mc_photo_file_path(row["photo_path"])
    try:
        is_file = file_path is not None and os.path.isfile(file_path)
    except (OSError, ValueError):
        is_file = False
    if not is_file:
        raise HTTPException(status_code=404, detail="MC photo not found")

    return FileResponse(file_path, media_type="image/webp")
