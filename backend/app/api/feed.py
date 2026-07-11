"""RSS 2.0 / iTunes ポッドキャストフィード配信"""

import os
import xml.etree.ElementTree as ET
from email.utils import formatdate
from typing import Optional

from fastapi import APIRouter, Response

from app.config import get_settings
from app.services.episode_service import EpisodeService, build_radio_title

router = APIRouter()

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

PROGRAM_NAME = "MyNews Radio"


def _episodes_base_dir() -> str:
    return os.environ.get("EPISODES_DIR", "data/episodes")


def _resolve_episode_directory(episode: dict) -> str:
    base = _episodes_base_dir()
    id_dir = os.path.join(base, str(episode.get("id", "")))
    if os.path.isdir(id_dir):
        return id_dir

    episode_date = episode.get("episode_date") or ""
    date_dir = os.path.join(base, episode_date)
    if os.path.isdir(date_dir):
        return date_dir

    return id_dir


def _format_rss_date(updated_at: str) -> str:
    try:
        from datetime import datetime

        dt = datetime.strptime(updated_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
        return formatdate(dt.timestamp(), usegmt=True)
    except (ValueError, OSError):
        return formatdate(usegmt=True)


def _get_audio_file_size(episode: dict) -> int:
    base_dir = _resolve_episode_directory(episode)
    audio_path = episode.get("audio_path", "")
    if not audio_path or not os.path.isdir(base_dir):
        return 0
    full_path = os.path.join(base_dir, audio_path)
    if os.path.isfile(full_path):
        return os.path.getsize(full_path)
    return 0


def _build_absolute_audio_url(episode: dict, rss_base_url: str) -> Optional[str]:
    audio_path = episode.get("audio_path")
    if not audio_path:
        return None
    base_dir = _resolve_episode_directory(episode)
    if not os.path.isdir(base_dir):
        return None
    dir_name = os.path.basename(base_dir)
    if not dir_name:
        return None
    base = rss_base_url.rstrip("/")
    return f"{base}/audio/{dir_name}/{audio_path}"


def _build_item_title(episode: dict) -> str:
    seq = episode.get("seq", 0) or 0
    episode_date = episode.get("episode_date", "")
    return build_radio_title(PROGRAM_NAME, episode_date, seq)


def _build_rss_xml() -> bytes:
    settings = get_settings()
    service = EpisodeService()
    episodes = service.get_completed_episodes_for_feed()

    rss = ET.Element("rss", {"version": "2.0", "xmlns:itunes": ITUNES_NS})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = PROGRAM_NAME
    ET.SubElement(channel, "link").text = settings.rss_base_url
    ET.SubElement(channel, "description").text = PROGRAM_NAME
    ET.SubElement(channel, "language").text = "ja"

    for ep in episodes:
        audio_url = _build_absolute_audio_url(ep, settings.rss_base_url)
        if not audio_url or not ep.get("audio_path"):
            continue

        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = _build_item_title(ep) or ""
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = str(ep["id"])
        ET.SubElement(item, "pubDate").text = _format_rss_date(ep.get("updated_at", ""))

        file_size = _get_audio_file_size(ep)
        ET.SubElement(item, "enclosure", {
            "url": audio_url,
            "type": "audio/mpeg",
            "length": str(file_size),
        })

        ET.SubElement(item, "description").text = ""

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


@router.get("/feed.xml")
def get_feed() -> Response:
    """ポッドキャストRSSフィードを返す"""
    xml_bytes = _build_rss_xml()
    return Response(content=xml_bytes, media_type="application/rss+xml")
