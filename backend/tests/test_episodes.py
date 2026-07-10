"""Tests for episodes CRUD and API responses with type/source_url columns."""


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

        resp = client.get("/episodes")
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
        svc.create_episode(episode_date="2099-12-31", type="commentary", source_url="https://example.com/latest")

        resp = client.get("/episodes/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "commentary"
        assert data["source_url"] == "https://example.com/latest"


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
        resp = client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_paginated_response_shape(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=3&offset=0")
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
        resp = client.get("/episodes?limit=3&offset=6")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        assert data["total"] == 10
        assert data["has_next"] is True

    def test_pagination_last_page(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=3&offset=9")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 10
        assert data["has_next"] is False

    def test_pagination_exact_fit(self, client):
        self._create_n_episodes(10)
        resp = client.get("/episodes?limit=10&offset=0")
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
        resp = client.get("/episodes?limit=5&offset=0")
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
