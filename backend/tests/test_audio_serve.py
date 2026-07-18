"""Tests for /audio/{episode_path:path} endpoint path traversal prevention."""

import json
import os


class TestAudioServeNormal:
    """正常系: 音声ファイルが正しく配信されることを確認する。"""

    def test_serve_2part_path(self, client, tmp_path):
        """2パート構成 /audio/<dir>/<file> の正常系"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "test-episode"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("dummy audio content")

        resp = client.get("/audio/test-episode/episode.mp3")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "audio/mpeg"

    def test_serve_1part_path(self, client, tmp_path):
        """1パート構成 /audio/<dir> の正常系"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "test-episode-1"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("dummy audio content")

        resp = client.get("/audio/test-episode-1")
        assert resp.status_code == 200

    def test_serve_with_metadata_json(self, client, tmp_path):
        """metadata.json の audio_path から解決されるケース"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "meta-episode"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "custom.mp3"
        audio_file.write_text("dummy audio content")
        with open(ep_sub / "metadata.json", "w") as f:
            json.dump({"audio_path": "custom.mp3"}, f)

        resp = client.get("/audio/meta-episode")
        assert resp.status_code == 200

    def test_date_based_fallback(self, client, tmp_path):
        """id-based path が date-based directory にフォールバックする正常系"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        ep_dir = tmp_path / "episodes"
        date_dir = ep_dir / "2099-12-31"
        date_dir.mkdir(parents=True)
        audio_file = date_dir / "episode.mp3"
        audio_file.write_text("dummy audio content")

        resp = client.get(f"/audio/{eid}/episode.mp3")
        assert resp.status_code == 200


class TestAudioServePathTraversal:
    """異常系: パストラバーサル攻撃が 404 になることを確認する。"""

    def test_path_traversal_dotdot(self, client, tmp_path):
        """../ で EPISODES_DIR 外を参照 → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/../etc/passwd")
        assert resp.status_code == 404

    def test_path_traversal_dotdot_absolute(self, client, tmp_path):
        """../ で EPISODES_DIR 外のファイルを指定 → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/../../etc/passwd")
        assert resp.status_code == 404

    def test_path_traversal_legit_dir_outside_file(self, client, tmp_path):
        """有効なディレクトリ名だがファイルが ../../ で外を指す → 404"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "legit"
        ep_sub.mkdir(parents=True)
        (ep_sub / "episode.mp3").write_text("dummy")

        resp = client.get("/audio/legit/../../etc/passwd")
        assert resp.status_code == 404

    def test_path_traversal_absolute_path(self, client, tmp_path):
        """絶対パスで EPISODES_DIR 外を指定 → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio//etc/passwd")
        assert resp.status_code == 404

    def test_path_traversal_urlencoded_dotdot(self, client, tmp_path):
        """URLエンコードされた %2e%2e%2f で外を参照 → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/%2e%2e%2fetc%2fpasswd")
        assert resp.status_code == 404

    def test_1part_path_traversal_dotdot(self, client, tmp_path):
        """1パート構成で ../ を指定 → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/../")
        assert resp.status_code == 404


class TestAudioServeNonExistent:
    """存在しないファイルの正常ケース"""

    def test_404_when_file_not_found(self, client, tmp_path):
        """存在しない音声ファイル → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/nonexistent/episode.mp3")
        assert resp.status_code == 404

    def test_date_based_fallback_unknown_id(self, client, tmp_path):
        """存在しないエピソードIDで date-based fallback → 404"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
        resp = client.get("/audio/99999/episode.mp3")
        assert resp.status_code == 404


CACHE_CONTROL = "public, max-age=31536000, immutable"


class TestAudioServeCacheControl:
    """キャッシュ制御とRangeリクエストのテスト"""

    def test_cache_control_on_normal_get(self, client, tmp_path):
        """通常GETで Cache-Control が public, max-age=31536000, immutable であること"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "cache-test"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("x" * 1000)

        resp = client.get("/audio/cache-test/episode.mp3")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == CACHE_CONTROL

    def test_range_request_returns_206_with_standard_headers(self, client, tmp_path):
        """Rangeリクエストで206 + Content-Range/Accept-Ranges/Content-Type が既存互換を保つこと"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "range-test"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("x" * 1000)

        resp = client.get(
            "/audio/range-test/episode.mp3",
            headers={"Range": "bytes=0-99"},
        )
        assert resp.status_code == 206
        assert resp.headers.get("content-range") == "bytes 0-99/1000"
        assert resp.headers.get("accept-ranges") == "bytes"
        assert resp.headers.get("content-type") == "audio/mpeg"
        assert resp.headers.get("content-length") == "100"

    def test_cache_control_on_range_request(self, client, tmp_path):
        """Rangeリクエスト時のCache-Controlも public, max-age=31536000, immutable であること"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "range-cache"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("x" * 1000)

        resp = client.get(
            "/audio/range-cache/episode.mp3",
            headers={"Range": "bytes=0-99"},
        )
        assert resp.status_code == 206
        assert resp.headers.get("cache-control") == CACHE_CONTROL

    def test_invalid_range_returns_416(self, client, tmp_path):
        """不正Range (bytes=a-b) で416が返ること"""
        ep_dir = tmp_path / "episodes"
        ep_sub = ep_dir / "invalid-range"
        ep_sub.mkdir(parents=True)
        audio_file = ep_sub / "episode.mp3"
        audio_file.write_text("x" * 1000)

        resp = client.get(
            "/audio/invalid-range/episode.mp3",
            headers={"Range": "bytes=a-b"},
        )
        assert resp.status_code == 416

    def test_404_no_cache_control(self, client, tmp_path):
        """存在しないファイルで404が返り、Cache-Controlヘッダが付与されないこと"""
        (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)

        resp = client.get("/audio/nonexistent/episode.mp3")
        assert resp.status_code == 404
        assert resp.headers.get("cache-control") is None
