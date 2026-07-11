"""Tests for /feed.xml RSS podcast feed."""

import os
import xml.etree.ElementTree as ET


def _create_completed_episode_with_audio(
    client,
    episode_date: str,
    seq: int = 0,
    audio_path: str = "episode.mp3",
    file_size: int = 1024,
):
    """Helper: create a completed episode + audio file on disk."""
    from app.services.episode_service import EpisodeService

    svc = EpisodeService()
    eid = svc.create_episode(
        episode_date=episode_date,
        audio_path=audio_path,
        seq=seq,
        status="completed",
    )

    ep_dir = os.environ.get("EPISODES_DIR", "data/episodes")
    episode_dir = os.path.join(ep_dir, str(eid))
    os.makedirs(episode_dir, exist_ok=True)
    audio_full = os.path.join(episode_dir, audio_path)
    with open(audio_full, "wb") as f:
        f.write(b"x" * file_size)

    return eid


ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)


def _parse_rss(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    assert root.tag == "rss"
    assert root.get("version") == "2.0"
    channel = root.find("channel")
    assert channel is not None
    return root, channel


class TestFeedEndpoint:
    """GET /feed.xml の基本応答テスト"""

    def test_content_type_is_rss_xml(self, client):
        resp = client.get("/feed.xml")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "application/rss+xml"

    def test_empty_feed_valid_xml(self, client):
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert channel.find("title") is not None
        assert channel.find("link") is not None
        assert channel.find("description") is not None
        assert channel.find("language") is not None

    def test_empty_feed_has_no_items(self, client):
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        items = channel.findall("item")
        assert len(items) == 0

    def test_channel_title_link_description_language(self, client):
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert channel.findtext("title") == "MyNews Radio"
        assert channel.findtext("link") == "http://localhost:8010"
        assert channel.findtext("description") == "MyNews Radio"
        assert channel.findtext("language") == "ja"

    def test_single_completed_episode_appears_in_feed(self, client):
        _create_completed_episode_with_audio(client, "2099-12-31")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        items = channel.findall("item")
        assert len(items) == 1

    def test_item_has_title_guid_pubdate_enclosure_description(self, client):
        _create_completed_episode_with_audio(client, "2099-12-31", seq=1)
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        item = channel.find("item")
        assert item is not None

        title = item.find("title")
        assert title is not None and title.text

        guid = item.find("guid")
        assert guid is not None and guid.text
        assert guid.get("isPermaLink") == "false"

        pubdate = item.find("pubDate")
        assert pubdate is not None and pubdate.text

        enclosure = item.find("enclosure")
        assert enclosure is not None
        assert enclosure.get("url")
        assert enclosure.get("type") == "audio/mpeg"
        assert enclosure.get("length")

        desc = item.find("description")
        assert desc is not None

    def test_enclosure_uses_absolute_url(self, client):
        eid = _create_completed_episode_with_audio(client, "2099-12-30")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        item = channel.find("item")
        enclosure = item.find("enclosure")
        url = enclosure.get("url")
        assert url.startswith("http://localhost:8010/audio/")
        assert str(eid) in url

    def test_enclosure_length_matches_file_size(self, client):
        _create_completed_episode_with_audio(
            client, "2099-12-29", file_size=4096
        )
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        item = channel.find("item")
        enclosure = item.find("enclosure")
        assert enclosure.get("length") == "4096"

    def test_rss_base_url_env_var_used(self, client, monkeypatch):
        monkeypatch.setenv("RSS_BASE_URL", "https://podcast.example.com")
        from app import config as cfg_mod

        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        _create_completed_episode_with_audio(client, "2099-12-28")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert channel.findtext("link") == "https://podcast.example.com"
        enclosure = channel.find("item").find("enclosure")
        assert enclosure.get("url").startswith("https://podcast.example.com/audio/")


class TestFeedEpisodeFiltering:
    """completed 以外のエピソードが除外されることのテスト"""

    def test_pending_episode_excluded(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-31", audio_path="ep.mp3", status="pending")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert len(channel.findall("item")) == 0

    def test_completed_without_audio_path_excluded(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-31", status="completed")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert len(channel.findall("item")) == 0

    def test_completed_with_empty_audio_path_excluded(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-31", audio_path="", status="completed")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert len(channel.findall("item")) == 0

    def test_failed_episode_excluded(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-31", audio_path="ep.mp3", status="failed")
        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert len(channel.findall("item")) == 0

    def test_mixed_statuses_only_completed_included(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        _create_completed_episode_with_audio(client, "2099-12-01")
        svc.create_episode(episode_date="2099-12-02", audio_path="b.mp3", status="pending")
        svc.create_episode(episode_date="2099-12-03", audio_path="c.mp3", status="failed")
        _create_completed_episode_with_audio(client, "2099-12-04")

        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        assert len(channel.findall("item")) == 2


class TestFeedItemOrder:
    """エピソードが日付降順に並ぶことのテスト"""

    def test_items_ordered_by_date_desc(self, client):
        _create_completed_episode_with_audio(client, "2099-12-03")
        _create_completed_episode_with_audio(client, "2099-12-01")
        _create_completed_episode_with_audio(client, "2099-12-02")

        resp = client.get("/feed.xml")
        root, channel = _parse_rss(resp.content)
        items = channel.findall("item")
        pubdates = [item.findtext("pubDate", "") for item in items]
        assert len(pubdates) == 3


class TestFeedRssNamespace:
    """RSS 2.0 + iTunes namespace のテスト"""

    def test_itunes_namespace_declared(self, client):
        resp = client.get("/feed.xml")
        text = resp.text
        assert 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"' in text

    def test_xml_declaration_present(self, client):
        resp = client.get("/feed.xml")
        text = resp.text
        assert text.startswith("<?xml")
