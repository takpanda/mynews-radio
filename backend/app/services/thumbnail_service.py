"""Client and persistence for the asynchronous .102 thumbnail service."""

import contextlib
import fcntl
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 表示サイズの約2倍（一覧カード: 高さ9.5rem、詳細: max-w-xl）。(ファイル名, 最大幅px)
THUMBNAIL_VARIANTS: dict[str, tuple[str, int]] = {
    "card": ("thumbnail-card.webp", 640),
    "detail": ("thumbnail-detail.webp", 1200),
}
_WEBP_QUALITY = 80


def _load_script(episode_id: int, episodes_dir: str | None = None) -> dict:
    root = episodes_dir or os.environ.get("EPISODES_DIR", "data/episodes")
    with open(os.path.join(root, str(episode_id), "script.json"), encoding="utf-8") as f:
        return json.load(f)


def _get_image(
    title: str, topic: str, settings, brand: str | None = None, *, episode_id: int | None = None,
    key_points: list[str] | None = None, source_articles: list[dict] | None = None,
) -> bytes:
    base_url = settings.thumbnail_service_url.rstrip("/")
    timeout = settings.thumbnail_http_timeout
    started = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/thumbnail",
            json={
                "episode_id": episode_id,
                "title": title,
                "topic": topic,
                "subtitle": topic,
                "key_points": key_points or [],
                "source_articles": source_articles or [],
                "brand": brand,
            },
            timeout=settings.thumbnail_enqueue_timeout,
        )
        response.raise_for_status()
        data = response.json()
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
            raise ValueError("thumbnail service returned an invalid job_id")

        while True:
            if time.monotonic() - started >= settings.thumbnail_job_timeout:
                raise TimeoutError("thumbnail job timed out")
            status_response = client.get(f"{base_url}/thumbnail/{quote(job_id, safe='')}")
            status_response.raise_for_status()
            status_data = status_response.json()
            status = status_data.get("status") if isinstance(status_data, dict) else None
            if status in {"completed", "complete", "succeeded", "success", "done"}:
                break
            if status in {"failed", "error"}:
                detail = status_data.get("error") if isinstance(status_data, dict) else None
                if not isinstance(detail, str) or not detail.strip():
                    detail = "no error details"
                raise RuntimeError(f"thumbnail job failed: {detail[:500]}")
            if not isinstance(status, str):
                raise ValueError("thumbnail service returned an invalid job status")
            remaining = max(
                0.0,
                settings.thumbnail_job_timeout - (time.monotonic() - started),
            )
            time.sleep(min(settings.thumbnail_poll_interval, remaining))

        image_response = client.get(f"{base_url}/files/{quote(job_id, safe='')}.png")
        image_response.raise_for_status()
        if not image_response.content:
            raise ValueError("thumbnail service returned an empty image")
        return image_response.content


def _resolve_brand(episode: dict) -> str | None:
    snapshot = episode.get("program_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError):
            snapshot = None
    if isinstance(snapshot, dict):
        name = snapshot.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    program_id = episode.get("program_id")
    if program_id is None:
        return None
    with get_db_connection() as conn:
        row = conn.execute("SELECT name FROM programs WHERE id = ?", (program_id,)).fetchone()
    if row and isinstance(row["name"], str) and row["name"].strip():
        return row["name"].strip()
    return None


def _resolve_source_articles(episode_id: int) -> list[dict]:
    """Return the episode's source article titles in their displayed order."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT a.id, a.title
            FROM episode_items ei JOIN articles a ON a.id = ei.article_id
            WHERE ei.episode_id = ?
            ORDER BY ei.item_order ASC
            LIMIT 8
            """,
            (episode_id,),
        ).fetchall()
    return [{"id": row["id"], "title": row["title"]} for row in rows]


@contextlib.contextmanager
def _episode_thumbnail_lock(directory: Path):
    """同じ回のサムネイル書き込み（PNG差し替え＋縮小版生成）をプロセス間で直列化する。"""
    with open(directory / ".thumbnail.lock", "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def generate_thumbnail_variants(png_path: str | Path) -> list[str]:
    """原寸PNGから縮小版WebPを生成する。失敗時は古い縮小版を残さず例外を送出する。

    ロック内でPNGを読むため、並行する上書き再生成と競合しても旧PNG由来のWebPが後から残らない。
    """
    png_path = Path(png_path)
    with _episode_thumbnail_lock(png_path.parent):
        return _write_thumbnail_variants(png_path)


def _write_thumbnail_variants(png_path: Path) -> list[str]:
    from PIL import Image

    written: list[str] = []
    try:
        with Image.open(png_path) as src:
            src.load()
            for filename, max_width in THUMBNAIL_VARIANTS.values():
                image = src.copy()
                if image.width > max_width:
                    image.thumbnail((max_width, image.height * max_width), Image.LANCZOS)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                target = png_path.with_name(filename)
                fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".thumbnail-", suffix=".tmp")
                os.close(fd)
                try:
                    image.save(temp_name, "WEBP", quality=_WEBP_QUALITY, method=6)
                    os.replace(temp_name, target)
                    temp_name = None
                finally:
                    if temp_name and os.path.exists(temp_name):
                        os.unlink(temp_name)
                written.append(str(target))
    except Exception:
        # 原寸PNGと食い違う古い縮小版を配信し続けないよう削除する
        for filename, _ in THUMBNAIL_VARIANTS.values():
            png_path.with_name(filename).unlink(missing_ok=True)
        raise
    return written


def generate_thumbnail(
    episode_id: int,
    *,
    title: str | None = None,
    topic: str | None = None,
    episodes_dir: str | None = None,
    overwrite: bool = False,
) -> str:
    """Generate and persist one episode thumbnail. Does not change episode status or notify."""
    service = EpisodeService()
    episode = service.get_episode(episode_id)
    if episode is None:
        raise ValueError(f"episode {episode_id} does not exist")

    script = _load_script(episode_id, episodes_dir)
    resolved_title = (title or script.get("title") or "").strip()
    resolved_topic = (topic or script.get("topic") or script.get("subtitle") or "").strip()
    if not resolved_title:
        raise ValueError("episode title is missing from script.json")
    if not resolved_topic:
        resolved_topic = resolved_title

    root = Path(episodes_dir or os.environ.get("EPISODES_DIR", "data/episodes"))
    output = root / str(episode_id) / "thumbnail.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and (output.exists() or episode.get("thumbnail_path")):
        raise FileExistsError(f"episode {episode_id} already has a thumbnail; pass --overwrite")

    raw_key_points = episode.get("key_points")
    if isinstance(raw_key_points, str):
        try:
            raw_key_points = json.loads(raw_key_points)
        except (TypeError, ValueError):
            raw_key_points = []
    key_points = raw_key_points if isinstance(raw_key_points, list) else []
    image = _get_image(
        resolved_title,
        resolved_topic,
        get_settings(),
        _resolve_brand(episode),
        episode_id=episode_id,
        key_points=key_points,
        source_articles=_resolve_source_articles(episode_id),
    )
    # PNG差し替えと縮小版生成を同一ロックで行い、一括生成との競合で古いWebPを残さない
    with _episode_thumbnail_lock(output.parent):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".thumbnail-", suffix=".tmp", delete=False) as f:
                temp_path = f.name
                f.write(image)
            os.replace(temp_path, output)
            temp_path = None
            service.update_episode_thumbnail_path(episode_id, "thumbnail.png")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        # 縮小版は付加的な最適化のため、失敗しても原寸PNGでの配信にフォールバックする
        try:
            _write_thumbnail_variants(output)
        except Exception:
            logger.exception("thumbnail variant generation failed: episode_id=%d", episode_id)
    return str(output)


def start_thumbnail_generation(
    episode_id: int,
    *,
    title: str | None = None,
    topic: str | None = None,
) -> None:
    """Start a non-blocking best-effort thumbnail worker after episode completion."""
    import threading

    def worker() -> None:
        try:
            path = generate_thumbnail(episode_id, title=title, topic=topic)
            logger.info("thumbnail generated: episode_id=%d path=%s", episode_id, path)
        except Exception:
            logger.exception("thumbnail generation failed: episode_id=%d", episode_id)

    thread = threading.Thread(target=worker, name=f"thumbnail-{episode_id}", daemon=False)
    thread.start()
