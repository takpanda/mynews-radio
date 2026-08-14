"""Tests for episodes CRUD and API responses with type/source_url columns."""

import os as _os


def _write_audio_file(ep_dir: str, episode_id, filename: str) -> None:
    """公開判定が実ファイルの存在まで確認するため、テストでもaudio_pathに対応する実ファイルを作る。"""
    d = _os.path.join(ep_dir, str(episode_id))
    _os.makedirs(d, exist_ok=True)
    with open(_os.path.join(d, filename), "wb") as f:
        f.write(b"dummy audio")


class TestEpisodeCreateWithTypeSourceUrl:
    """create_episode() に type/source_url を渡すケースのテスト"""

    def test_create_with_commentary_and_source_url(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/article",
        )
        ep = svc.get_episode(eid)
        assert ep is not None
        assert ep["type"] == "commentary"
        assert ep["source_url"] == "https://example.com/article"

    def test_default_type_is_radio_source_url_is_none(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-02")
        ep = svc.get_episode(eid)
        assert ep is not None
        assert ep["type"] == "radio"
        assert ep["source_url"] is None

    def test_create_with_commentary_in_list(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-03", type="radio")
        svc.create_episode(episode_date="2099-12-04", type="commentary", source_url="https://example.com/news")
        episodes = svc.get_episode_list()
        commentary = [e for e in episodes if e["type"] == "commentary"]
        assert len(commentary) == 1
        assert commentary[0]["source_url"] == "https://example.com/news"


class TestEpisodeApiTypeSourceUrl:
    """API エンドポイントのレスポンスに type/source_url が含まれることのテスト"""

    def test_list_episodes_contains_type_source_url(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-10", type="radio")
        svc.create_episode(episode_date="2099-12-11", type="commentary", source_url="https://example.com/a")

        resp = client.get("/episodes?include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

        for ep in data:
            assert "type" in ep
            assert "source_url" in ep

        commentary = [e for e in data if e["type"] == "commentary"]
        assert len(commentary) >= 1
        assert commentary[0]["source_url"] == "https://example.com/a"

    def test_detail_episode_contains_type_source_url(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(
            episode_date="2099-12-20",
            type="commentary",
            source_url="https://example.com/detail",
        )

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "commentary"
        assert data["source_url"] == "https://example.com/detail"

    def test_latest_episode_contains_type_source_url(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-30", type="radio")
        eid = svc.create_episode(episode_date="2099-12-31", type="commentary", source_url="https://example.com/latest", audio_path="latest.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, eid, "latest.mp3")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "commentary"
        assert data["source_url"] == "https://example.com/latest"


class TestEpisodeGeneratedAt:
    """GET /episodes/{id} の generated_at フィールドのテスト"""

    def test_detail_episode_contains_generated_at(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(
            episode_date="2099-12-20",
            type="radio",
        )
        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "generated_at" in data

    def test_generated_at_matches_updated_at(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-21")
        ep = svc.get_episode(eid)
        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["generated_at"] == ep["updated_at"]

    def test_generated_at_in_script_endpoint(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        ep_script_dir = _os.path.join(ep_dir, str(eid))
        _os.makedirs(ep_script_dir, exist_ok=True)
        with open(_os.path.join(ep_script_dir, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": "t", "subtitle": "", "lines": []}, f)
        resp = client.get(f"/episodes/{eid}/script")
        assert resp.status_code == 200
        data = resp.json()
        assert "generated_at" in data


class TestEpisodeScriptEndpoint:
    """GET /episodes/{id}/script のレスポンス形式テスト"""

    def test_get_script_returns_formatted_response(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        ep_script_dir = _os.path.join(ep_dir, str(eid))
        _os.makedirs(ep_script_dir, exist_ok=True)

        script_data = {
            "title": "テスト番組",
            "subtitle": "テスト用サブタイトル",
            "lines": [
                {"speaker": "male", "text": "こんにちは", "section": "intro"},
                {"speaker": "female", "text": "こんばんは", "section": "news"},
            ],
        }
        with open(_os.path.join(ep_script_dir, "script.json"), "w", encoding="utf-8") as f:
            _json.dump(script_data, f)

        resp = client.get(f"/episodes/{eid}/script")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            f"ep_dir={ep_dir}, script_dir={ep_script_dir}, "
            f"env_episodes_dir={_os.environ.get('EPISODES_DIR')}"
        )
        data = resp.json()

        assert data["id"] == eid
        assert data["episode_date"] == "2099-12-31"
        assert data["title"] == "テスト番組"
        assert data["subtitle"] == "テスト用サブタイトル"
        assert len(data["lines"]) == 2
        assert data["lines"][0]["speaker"] == "male"
        assert data["lines"][0]["text"] == "こんにちは"
        assert data["lines"][1]["speaker"] == "female"
        assert data["lines"][1]["text"] == "こんばんは"
        assert "generated_at" in data

    def test_get_script_404_when_no_script_file(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        resp = client.get(f"/episodes/{eid}/script")
        assert resp.status_code == 404

    def test_get_script_404_when_episode_not_found(self, client):
        resp = client.get("/episodes/99999/script")
        assert resp.status_code == 404


class TestEpisodeReviewEndpoint:
    """GET /episodes/{id}/review のレスポンス形式テスト"""

    def test_get_review_new_path(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        review_dir = _os.path.join(ep_dir, str(eid), "review")
        _os.makedirs(review_dir, exist_ok=True)

        review_data = {"reviewer": "test_reviewer", "feedback": "ok", "score": 85}
        with open(_os.path.join(review_dir, "review.json"), "w", encoding="utf-8") as f:
            _json.dump(review_data, f)

        resp = client.get(f"/episodes/{eid}/review")
        assert resp.status_code == 200
        assert resp.json() == review_data

    def test_get_review_fallback_old_path(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        ep_episode_dir = _os.path.join(ep_dir, str(eid))
        _os.makedirs(ep_episode_dir, exist_ok=True)

        review_data = {"reviewer": "legacy", "feedback": "old path"}
        with open(_os.path.join(ep_episode_dir, "review.json"), "w", encoding="utf-8") as f:
            _json.dump(review_data, f)

        resp = client.get(f"/episodes/{eid}/review")
        assert resp.status_code == 200
        assert resp.json() == review_data

    def test_get_review_new_path_preferred_over_old(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        ep_episode_dir = _os.path.join(ep_dir, str(eid))
        _os.makedirs(ep_episode_dir, exist_ok=True)

        old_data = {"reviewer": "old", "feedback": "old path"}
        with open(_os.path.join(ep_episode_dir, "review.json"), "w", encoding="utf-8") as f:
            _json.dump(old_data, f)

        review_dir = _os.path.join(ep_dir, str(eid), "review")
        _os.makedirs(review_dir, exist_ok=True)
        new_data = {"reviewer": "new", "feedback": "new path preferred"}
        with open(_os.path.join(review_dir, "review.json"), "w", encoding="utf-8") as f:
            _json.dump(new_data, f)

        resp = client.get(f"/episodes/{eid}/review")
        assert resp.status_code == 200
        assert resp.json() == new_data

    def test_get_review_404_when_no_review_file(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-31")

        resp = client.get(f"/episodes/{eid}/review")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Review file not found"

    def test_get_review_404_when_episode_not_found(self, client):
        resp = client.get("/episodes/99999/review")
        assert resp.status_code == 404


class TestEpisodeDetailScriptReviewPublicBoundary:
    """GET /episodes/{id}, /script, /review の公開/管理境界のテスト"""

    def _create_script_json(self, ep_dir: str, episode_id: int, title: str = "タイトル"):
        import json as _json
        import os as _os
        d = _os.path.join(ep_dir, str(episode_id))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": title, "subtitle": "", "lines": []}, f)

    def test_detail_404_for_unauthenticated_when_not_completed(self):
        """未認証は生成中・失敗・下書きエピソードの詳細を取得できない"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-01", audio_path="test.mp3")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}")

        assert resp.status_code == 404

    def test_detail_200_for_unauthenticated_when_completed(self):
        """未認証でも完成済みで再生可能なエピソードの詳細は取得できる"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-02", audio_path="test.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, eid, "test.mp3")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_detail_404_for_unauthenticated_when_audio_file_missing(self):
        """完成済み・DBにaudio_pathがあっても、実ファイルが欠損していれば未認証には404"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-09", audio_path="missing.mp3", status="completed")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}")

        assert resp.status_code == 404

    def test_detail_200_for_owner_when_audio_file_missing(self, client):
        """音声ファイルが欠損していても、オーナー認証済みの管理経路では詳細を取得できる"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-10", audio_path="missing.mp3", status="completed")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_detail_200_for_owner_when_not_completed(self, client):
        """オーナー認証済みの管理経路では生成中エピソードの詳細を取得できる"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-03")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_script_404_for_unauthenticated_when_not_completed(self):
        """未認証は生成中エピソードの台本を取得できない"""
        import os as _os
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-04")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid)

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}/script")

        assert resp.status_code == 404

    def test_script_200_for_unauthenticated_when_completed(self):
        """未認証でも完成済みエピソードの台本は既存のリスナー体験どおり取得できる"""
        import os as _os
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-05", audio_path="test.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid, title="公開台本")
        _write_audio_file(ep_dir, eid, "test.mp3")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}/script")

        assert resp.status_code == 200
        assert resp.json()["title"] == "公開台本"

    def test_script_404_for_unauthenticated_when_audio_file_missing(self):
        """完成済み・DBにaudio_pathがあっても、実ファイルが欠損していれば未認証の台本取得は404"""
        import os as _os
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-11", audio_path="missing.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid, title="非公開台本")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}/script")

        assert resp.status_code == 404

    def test_script_200_for_owner_when_not_completed(self, client):
        """オーナー認証済みの管理経路では生成中エピソードの台本を取得できる"""
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-06")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid, title="管理用台本")

        resp = client.get(f"/episodes/{eid}/script")
        assert resp.status_code == 200
        assert resp.json()["title"] == "管理用台本"

    def test_review_401_for_unauthenticated_even_when_completed(self):
        """内部レビューは公開の利用箇所がないため、完成済みでも未認証には返さない"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-07", audio_path="test.mp3", status="completed")

        with TestClient(app) as public_client:
            resp = public_client.get(f"/episodes/{eid}/review")

        assert resp.status_code == 401

    def test_review_200_for_owner_when_not_completed(self, client):
        """オーナー認証済みの管理経路では生成中エピソードの内部レビューを取得できる"""
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-11-08")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        review_dir = _os.path.join(ep_dir, str(eid), "review")
        _os.makedirs(review_dir, exist_ok=True)
        review_data = {"reviewer": "owner", "feedback": "ok"}
        with open(_os.path.join(review_dir, "review.json"), "w", encoding="utf-8") as f:
            _json.dump(review_data, f)

        resp = client.get(f"/episodes/{eid}/review")
        assert resp.status_code == 200
        assert resp.json() == review_data


class TestEpisodeListPagination:
    """GET /episodes のページネーションテスト"""

    def _create_n_episodes(self, n: int):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        for i in range(n):
            svc.create_episode(
                episode_date=f"2099-12-{31 - i:02d}",
                type="radio",
            )

    def test_no_params_returns_all(self, client):
        self._create_n_episodes(5)
        resp = client.get("/episodes?include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_paginated_response_shape(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=3&offset=0&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data
        assert "has_next" in data
        assert len(data["items"]) == 3
        assert data["total"] == 10
        assert data["has_next"] is True

    def test_pagination_offset(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=3&offset=6&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        assert data["total"] == 10
        assert data["has_next"] is True

    def test_pagination_last_page(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=3&offset=9&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 10
        assert data["has_next"] is False

    def test_pagination_exact_fit(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=10&offset=0&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 10
        assert data["has_next"] is False

    def test_pagination_empty_result(self, client):
        resp = client.get("/episodes?limit=5&offset=100")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 0
        assert data["total"] == 0
        assert data["has_next"] is False

    def test_pagination_maintains_sort_order(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=5&offset=0&include_failed=true")
        data = resp.json()
        dates = [ep["date"] for ep in data["items"]]
        assert dates == sorted(dates, reverse=True), "日付降順になっていない"

    def test_limit_negative_rejected(self, client):
        resp = client.get("/episodes?limit=-1")
        assert resp.status_code == 422

    def test_limit_zero_rejected(self, client):
        resp = client.get("/episodes?limit=0")
        assert resp.status_code == 422

    def test_offset_negative_rejected(self, client):
        resp = client.get("/episodes?limit=5&offset=-1")
        assert resp.status_code == 422

    def test_offset_without_limit(self, client):
        self._create_n_episodes(5)
        resp = client.get("/episodes?offset=2&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_offset_exceeds_total(self, client):
        self._create_n_episodes(5)
        resp = client.get("/episodes?offset=10&include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_same_date_episodes_tie_break_by_id(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        for i in range(5):
            svc.create_episode(episode_date="2099-12-31", type="radio")
        episodes = svc.get_episode_list()
        ids = [ep["id"] for ep in episodes[:5]]
        assert ids == sorted(ids, reverse=True), "同日エピソードは id DESC で並ぶ必要があります"


class TestEpisodeKeyPoints:
    """エピソード詳細APIの key_points フィールドのテスト"""

    def test_detail_episode_contains_key_points(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-01")
        svc.update_episode_key_points(eid, ["ポイント1", "ポイント2", "ポイント3"])

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "key_points" in data
        assert data["key_points"] == ["ポイント1", "ポイント2", "ポイント3"]

    def test_key_points_empty_when_not_set(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-02")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key_points"] == []

    def test_key_points_max_3(self, client):
        """4件以上保存してもAPIレスポンスは最大3件まで"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-03")
        svc.update_episode_key_points(eid, ["A", "B", "C", "D"])

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["key_points"]) == 3
        assert data["key_points"] == ["A", "B", "C"]

    def test_key_points_single_item(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-04")
        svc.update_episode_key_points(eid, ["単一ポイント"])

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key_points"] == ["単一ポイント"]

    def test_latest_episode_contains_key_points(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-05", audio_path="test.mp3", status="completed")
        svc.update_episode_key_points(eid, ["最新のポイント"])
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, eid, "test.mp3")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert "key_points" in data
        assert data["key_points"] == ["最新のポイント"]

    def test_update_key_points_overwrites(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-06")
        svc.update_episode_key_points(eid, ["初期"])
        svc.update_episode_key_points(eid, ["更新後"])

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key_points"] == ["更新後"]


class TestAudioGenerationId:
    """エピソード詳細APIのレスポンスに audio_generation_id が含まれることのテスト"""

    def test_detail_episode_articles_contain_audio_generation_id(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-01")
        svc.add_episode_item(eid, article_id=None, item_order=1, segment_text="セグメント1",
                             audio_generation_id=f"ep{eid}-seg1")
        svc.add_episode_item(eid, article_id=None, item_order=2, segment_text="セグメント2",
                             audio_generation_id=f"ep{eid}-seg2")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "articles" in data
        assert len(data["articles"]) == 2
        for article in data["articles"]:
            assert "audio_generation_id" in article
        assert data["articles"][0]["audio_generation_id"] == f"ep{eid}-seg1"
        assert data["articles"][1]["audio_generation_id"] == f"ep{eid}-seg2"

    def test_add_episode_item_without_audio_generation_id(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-02")
        svc.add_episode_item(eid, article_id=None, item_order=1, segment_text="セグメント")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["articles"]) == 1
        assert data["articles"][0]["audio_generation_id"] is None

    def test_latest_episode_contains_audio_generation_id_when_db_items_exist(self, client):
        """GET /episodes/latest で DB に items がある場合に audio_generation_id が含まれること"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-03", audio_path="test.mp3", status="completed")
        svc.add_episode_item(eid, article_id=None, item_order=1, segment_text="最新セグメント1",
                             audio_generation_id=f"ep{eid}-seg1")
        svc.add_episode_item(eid, article_id=None, item_order=2, segment_text="最新セグメント2",
                             audio_generation_id=f"ep{eid}-seg2")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, eid, "test.mp3")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert "articles" in data
        assert len(data["articles"]) == 2
        for article in data["articles"]:
            assert "audio_generation_id" in article
        assert data["articles"][0]["audio_generation_id"] == f"ep{eid}-seg1"
        assert data["articles"][1]["audio_generation_id"] == f"ep{eid}-seg2"

    def test_generation_style_ids_are_non_null_and_unique(self, client):
        """生成パイプラインと同様のパターンで add_episode_item した時の ID 非NULL・一意性確認"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-04")
        ids = set()
        for i in range(1, 6):
            gen_id = f"ep{eid}-seg{i}"
            svc.add_episode_item(eid, article_id=None, item_order=i, segment_text=f"セグメント{i}",
                                 audio_generation_id=gen_id)
            ids.add(gen_id)

        assert len(ids) == 5, "5件のIDがすべて一意であること"
        assert None not in ids, "すべてのIDがNoneでないこと"

        items = svc.get_episode_items(eid)
        for item in items:
            assert item["audio_generation_id"] is not None
            assert item["audio_generation_id"].startswith(f"ep{eid}-seg")


class TestPublicArchiveFiltering:
    """公開アーカイブからの失敗エピソード除外のテスト"""

    def _create_script_json(self, ep_dir: str, episode_id: int, title: str):
        import json as _json
        import os as _os
        d = _os.path.join(ep_dir, str(episode_id))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": title, "subtitle": "", "lines": []}, f)

    def test_excludes_episode_without_audio_and_without_title(self, client, tmp_path):
        """音声がなくタイトルもないエピソードは公開アーカイブから除外される"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-01")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid not in ids

    def test_include_failed_requires_owner_session(self):
        """管理用の全件一覧は未認証クライアントに公開しない。"""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as public_client:
            resp = public_client.get("/episodes?include_failed=true")

        assert resp.status_code == 401

    def test_category_filter_uses_saved_categories(self, client):
        """公開カテゴリ検索はタイトルではなく保存済みcategoriesだけで判定する。"""
        import os as _os
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        tech_id = svc.create_episode(
            episode_date="2099-12-06",
            audio_path="tech.mp3",
            status="completed",
        )
        general_id = svc.create_episode(
            episode_date="2099-12-05",
            audio_path="general.mp3",
            status="completed",
        )
        svc.update_episode_categories(tech_id, ["テック・IT"])
        svc.update_episode_categories(general_id, ["社会・暮らし"])
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, tech_id, "tech.mp3")
        _write_audio_file(ep_dir, general_id, "general.mp3")

        resp = client.get("/episodes?category=tech")

        assert resp.status_code == 200
        assert [episode["id"] for episode in resp.json()] == [tech_id]

    def test_includes_episode_with_audio(self, client):
        """音声があるエピソードはタイトルがなくても公開アーカイブに表示される"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-02", audio_path="test.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        _write_audio_file(ep_dir, eid, "test.mp3")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid in ids

    def test_excludes_episode_with_audio_path_but_missing_file(self, client):
        """DBにaudio_pathがあっても実ファイルが欠損していれば公開アーカイブから除外される"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-08", audio_path="missing.mp3", status="completed")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid not in ids

    def test_excludes_episode_with_title_from_script_but_no_audio(self, client):
        """台本だけの生成中回は公開アーカイブに表示しない。"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-03")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid, "有効なタイトル")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid not in ids

    def test_excludes_episode_with_blank_title_in_script(self, client):
        """script.jsonのタイトルが空白のみの場合も除外される"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-04")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        self._create_script_json(ep_dir, eid, "   ")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid not in ids

    def test_include_failed_param_shows_all(self, client):
        """include_failed=true ですべてのエピソードが表示される"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-05")

        resp = client.get("/episodes?include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]
        assert eid in ids

    def test_pagination_with_filtering(self, client):
        """フィルタリングとページネーションの組み合わせ"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")

        # Create 10 episodes: 5 with audio (should appear), 5 without audio/title (should be filtered)
        audio_ids = []
        failed_ids = []
        for i in range(5):
            eid = svc.create_episode(episode_date=f"2099-12-{20 - i:02d}", audio_path=f"audio{i}.mp3", status="completed")
            _write_audio_file(ep_dir, eid, f"audio{i}.mp3")
            audio_ids.append(eid)
        for i in range(5):
            eid = svc.create_episode(episode_date=f"2099-12-{15 - i:02d}")
            failed_ids.append(eid)

        resp = client.get("/episodes?limit=3&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["has_next"] is True

        page_ids = [ep["id"] for ep in data["items"]]
        assert set(page_ids).issubset(set(audio_ids))

    def test_mixed_episodes_correct_filtering(self, client):
        """正常エピソード・音声のみ・タイトルのみ・失敗エピソードの混合テスト"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")

        e1 = svc.create_episode(episode_date="2099-12-01", audio_path="e1.mp3", status="completed")
        _write_audio_file(ep_dir, e1, "e1.mp3")
        e2 = svc.create_episode(episode_date="2099-12-02")
        self._create_script_json(ep_dir, e2, "タイトルのみ")
        e3 = svc.create_episode(episode_date="2099-12-03", audio_path="e3.mp3", status="completed")
        self._create_script_json(ep_dir, e3, "音声＋タイトル")
        _write_audio_file(ep_dir, e3, "e3.mp3")
        e4 = svc.create_episode(episode_date="2099-12-04")
        e5 = svc.create_episode(episode_date="2099-12-05", audio_path="e5.mp3", status="completed")
        self._create_script_json(ep_dir, e5, "  ")
        _write_audio_file(ep_dir, e5, "e5.mp3")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        ids = [ep["id"] for ep in data]

        assert e1 in ids
        assert e2 not in ids
        assert e3 in ids
        assert e4 not in ids
        assert e5 in ids

    def test_admin_include_failed_keeps_all_type_source_url(self, client):
        """include_failed=true でも type/source_url は正しく含まれる"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-01", type="commentary", source_url="https://example.com/adm")

        resp = client.get("/episodes?include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["type"] == "commentary"
        assert data[0]["source_url"] == "https://example.com/adm"

    def test_empty_public_archive_when_all_are_failed(self, client):
        """全エピソードが失敗の場合、公開アーカイブは空リストになる"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        for i in range(3):
            svc.create_episode(episode_date=f"2099-12-{i + 1:02d}")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_excludes_episode_with_null_title_in_script(self, client):
        """script.json の title が null の場合も除外される（AttributeError にならない）"""
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-01")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        d = _os.path.join(ep_dir, str(eid))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": None, "subtitle": "", "lines": []}, f)

        resp = client.get("/episodes")
        assert resp.status_code == 200
        ids = [ep["id"] for ep in resp.json()]
        assert eid not in ids

    def test_does_not_crash_on_null_title_in_list(self, client):
        """title が null の script.json でも GET /episodes が500にならない"""
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-01", audio_path="test.mp3", status="completed")
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        d = _os.path.join(ep_dir, str(eid))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": None, "subtitle": "", "lines": []}, f)
        _write_audio_file(ep_dir, eid, "test.mp3")

        resp = client.get("/episodes")
        assert resp.status_code == 200
        ids = [ep["id"] for ep in resp.json()]
        assert eid in ids

    def test_latest_skips_episode_with_missing_audio_file(self, client):
        """DBにaudio_pathがあっても実ファイルが欠損していれば/episodes/latestから除外される"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")

        eid_missing = svc.create_episode(episode_date="2099-12-10", audio_path="missing.mp3", status="completed")
        eid_playable = svc.create_episode(episode_date="2099-12-09", audio_path="playable.mp3", status="completed")
        _write_audio_file(ep_dir, eid_playable, "playable.mp3")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        assert resp.json()["id"] == eid_playable
        assert resp.json()["id"] != eid_missing

    def test_latest_skips_failed_episodes(self, client):
        """最新が失敗エピソードの場合、次点の公開可能エピソードが返る"""
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")

        eid_audio = svc.create_episode(episode_date="2099-12-01", audio_path="latest.mp3", status="completed")
        _write_audio_file(ep_dir, eid_audio, "latest.mp3")
        eid_failed = svc.create_episode(episode_date="2099-12-02")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == eid_audio

    def test_latest_returns_404_when_all_are_failed(self, client):
        """全エピソードが失敗の場合、/episodes/latest は404を返す"""
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        for i in range(3):
            svc.create_episode(episode_date=f"2099-12-{i + 1:02d}")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 404


class TestSearchEpisodesBySourceUrl:
    """GET /episodes/search/by-source-url のテスト"""

    def test_returns_matching_episodes(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-12-01", type="radio")
        eid = svc.create_episode(
            episode_date="2099-12-02",
            type="commentary",
            source_url="https://example.com/article",
        )
        svc.create_episode(
            episode_date="2099-12-03",
            type="commentary",
            source_url="https://example.com/other",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == eid
        assert data[0]["status"] == "pending"
        assert data[0]["type"] == "commentary"
        assert data[0]["source_url"] == "https://example.com/article"
        assert "created_at" in data[0]
        assert "title" in data[0]
        assert "has_script" in data[0]

    def test_returns_empty_when_no_match(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/nonexistent"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_multiple_matches(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        e1 = svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/article",
            status="completed",
        )
        e2 = svc.create_episode(
            episode_date="2099-12-02",
            type="commentary",
            source_url="https://example.com/article",
            status="failed",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        returned_ids = {ep["id"] for ep in data}
        assert e1 in returned_ids
        assert e2 in returned_ids

    def test_returns_all_statuses(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/article",
            status="pending",
        )
        svc.create_episode(
            episode_date="2099-12-02",
            type="commentary",
            source_url="https://example.com/article",
            status="generating",
        )
        svc.create_episode(
            episode_date="2099-12-03",
            type="commentary",
            source_url="https://example.com/article",
            status="completed",
        )
        svc.create_episode(
            episode_date="2099-12-04",
            type="commentary",
            source_url="https://example.com/article",
            status="failed",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        returned_statuses = {ep["status"] for ep in data}
        assert returned_statuses == {"pending", "generating", "completed", "failed"}

    def test_excludes_radio_episodes(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(
            episode_date="2099-12-01",
            type="radio",
            source_url="https://example.com/article",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_excludes_different_source_url(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/a",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/b"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_empty_string_returns_400(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": ""},
        )
        assert resp.status_code == 400

    def test_whitespace_only_returns_400(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "   "},
        )
        assert resp.status_code == 400

    def test_invalid_url_format_returns_400(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "not-a-url"},
        )
        assert resp.status_code == 400

    def test_missing_param_returns_422(self, client):
        resp = client.get("/episodes/search/by-source-url")
        assert resp.status_code == 422

    def test_invalid_url_scheme_only_https(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://"},
        )
        assert resp.status_code == 400

    def test_invalid_url_scheme_only_http(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "http://"},
        )
        assert resp.status_code == 400

    def test_invalid_url_no_scheme(self, client):
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "example.com"},
        )
        assert resp.status_code == 400

    def test_response_includes_title(self, client):
        import json as _json
        import os as _os
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        eid = svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/article",
            status="completed",
        )
        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        d = _os.path.join(ep_dir, str(eid))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "script.json"), "w", encoding="utf-8") as f:
            _json.dump({"title": "テスト解説", "subtitle": "", "lines": []}, f)

        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "テスト解説"
        assert data[0]["has_script"] is True

    def test_response_title_null_when_no_script(self, client):
        from app.services.episode_service import EpisodeService
        svc = EpisodeService()
        svc.create_episode(
            episode_date="2099-12-01",
            type="commentary",
            source_url="https://example.com/article",
            status="pending",
        )
        resp = client.get(
            "/episodes/search/by-source-url",
            params={"source_url": "https://example.com/article"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] is None
        assert data[0]["has_script"] is False


class TestEpisodeLlmInfo:
    """/episodes, /episodes/{id} レスポンスの llm_provider / llm_model のテスト"""

    def _write_metadata(self, episode_id, **fields):
        import json as _json
        import os as _os

        ep_dir = _os.environ.get("EPISODES_DIR", "data/episodes")
        d = _os.path.join(ep_dir, str(episode_id))
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
            _json.dump(fields, f)

    def test_detail_contains_llm_info_when_present(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-05")
        self._write_metadata(eid, llm_provider="ollama", llm_model="gpt-oss:20b")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_provider"] == "ollama"
        assert data["llm_model"] == "gpt-oss:20b"

    def test_detail_llm_info_null_when_metadata_missing(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-06")

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_provider"] is None
        assert data["llm_model"] is None

    def test_detail_llm_info_null_when_metadata_lacks_fields(self, client):
        """既存エピソード互換: metadata.json に llm_provider/llm_model キーがない場合"""
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-07")
        self._write_metadata(eid, duration_seconds=123.4)

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_provider"] is None
        assert data["llm_model"] is None
        # 既存フィールドへの影響がないことも確認
        assert data["duration_seconds"] == 123.4

    def test_list_contains_llm_info(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-08")
        self._write_metadata(eid, llm_provider="openai", llm_model="gpt-4o-mini")

        resp = client.get("/episodes?include_failed=true")
        assert resp.status_code == 200
        data = resp.json()
        target = next(e for e in data if e["id"] == eid)
        assert target["llm_provider"] == "openai"
        assert target["llm_model"] == "gpt-4o-mini"

    def test_applied_settings_unaffected_by_llm_info(self, client):
        from app.services.episode_service import EpisodeService

        svc = EpisodeService()
        eid = svc.create_episode(episode_date="2099-12-09")
        self._write_metadata(
            eid,
            llm_provider="ollama",
            llm_model="gpt-oss:20b",
            applied_settings={"tts_engine": "voicevox"},
        )

        resp = client.get(f"/episodes/{eid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied_settings"] == {"tts_engine": "voicevox"}
        assert data["llm_provider"] == "ollama"
        assert data["llm_model"] == "gpt-oss:20b"
