"""Client and persistence for the asynchronous .102 thumbnail service."""

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
from app.services.episode_service import EpisodeService

logger = logging.getLogger(__name__)
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _load_script(episode_id: int, episodes_dir: str | None = None) -> dict:
    root = episodes_dir or os.environ.get("EPISODES_DIR", "data/episodes")
    with open(os.path.join(root, str(episode_id), "script.json"), encoding="utf-8") as f:
        return json.load(f)


def _get_image(title: str, topic: str, settings) -> bytes:
    base_url = settings.thumbnail_service_url.rstrip("/")
    timeout = settings.thumbnail_http_timeout
    started = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/thumbnail",
            json={"title": title, "topic": topic},
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
                raise RuntimeError("thumbnail job failed")
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

    image = _get_image(resolved_title, resolved_topic, get_settings())
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
