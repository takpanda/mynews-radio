"""Tests for misreading report submission API (BEE-432)."""


class TestMisreadingReportCreate:
    """POST /reports/misreading のテスト"""

    def test_create_success_minimal(self, client):
        """必須項目のみで正常登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト文章",
                "correct_reading": "てすとぶんしょう",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_text"] == "テスト文章"
        assert data["correct_reading"] == "てすとぶんしょう"
        assert "id" in data
        assert "created_at" in data
        assert data["article_id"] is None
        assert data["audio_generation_id"] is None
        assert data["playback_position"] is None
        assert data["notes"] == ""

    def test_create_success_full(self, client):
        """全フィールド含めて正常登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "人工知能",
                "correct_reading": "じんこうちのう",
                "article_id": 42,
                "audio_generation_id": "gen_abc123",
                "playback_position": 120.5,
                "notes": "補足情報です",
                "app_version": "1.2.3",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_text"] == "人工知能"
        assert data["correct_reading"] == "じんこうちのう"
        assert data["article_id"] == 42
        assert data["audio_generation_id"] == "gen_abc123"
        assert data["playback_position"] == 120.5
        assert data["notes"] == "補足情報です"
        assert data["app_version"] == "1.2.3"

    def test_create_missing_target_text(self, client):
        """target_text が無い場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={"correct_reading": "てすと"},
        )
        assert resp.status_code == 422

    def test_create_missing_correct_reading(self, client):
        """correct_reading が無い場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={"target_text": "テスト"},
        )
        assert resp.status_code == 422

    def test_create_empty_target_text(self, client):
        """target_text が空文字の場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={"target_text": "", "correct_reading": "てすと"},
        )
        assert resp.status_code == 422

    def test_create_empty_correct_reading(self, client):
        """correct_reading が空文字の場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={"target_text": "テスト", "correct_reading": ""},
        )
        assert resp.status_code == 422

    def test_create_duplicate_within_24h(self, client):
        """同じ target_text + correct_reading を24時間以内に再送信すると 409"""
        resp1 = client.post(
            "/reports/misreading",
            json={"target_text": "重複テスト", "correct_reading": "ちょうふくてすと"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/reports/misreading",
            json={"target_text": "重複テスト", "correct_reading": "ちょうふくてすと"},
        )
        assert resp2.status_code == 409
        assert "duplicate" in resp2.json()["detail"].lower()

    def test_same_text_different_reading_ok(self, client):
        """同じ target_text でも correct_reading が異なれば登録できる"""
        resp1 = client.post(
            "/reports/misreading",
            json={"target_text": "東京", "correct_reading": "とうきょう"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/reports/misreading",
            json={"target_text": "東京", "correct_reading": "トウキョウ"},
        )
        assert resp2.status_code == 201

    def test_negative_playback_position_422(self, client):
        """playback_position が負の値の場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "playback_position": -1,
            },
        )
        assert resp.status_code == 422

    def test_invalid_article_id_type(self, client):
        """article_id に文字列を渡すと 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "article_id": "not-a-number",
            },
        )
        assert resp.status_code == 422

    def test_target_text_too_long(self, client):
        """target_text が2000文字を超えると 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "a" * 2001,
                "correct_reading": "てすと",
            },
        )
        assert resp.status_code == 422

    def test_reports_endpoint_no_auth_required(self, client, monkeypatch):
        """報告エンドポイントはAPIキー認証なしでアクセスできる"""
        monkeypatch.setenv("API_KEY", "test-secret-key")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.post(
            "/reports/misreading",
            json={"target_text": "テスト", "correct_reading": "てすと"},
        )
        assert resp.status_code == 201



