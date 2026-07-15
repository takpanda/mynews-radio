"""Tests for misreading report submission API (BEE-432)."""

import sqlite3

import pytest


def _seed_article(client, title="TestArticle"):
    """Helper: seed an article row directly in the test DB."""
    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO articles (title, status) VALUES (?, 'new')",
            (title,),
        )
        return cursor.lastrowid


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
        """全フィールド含めて正常登録できる（article_id は別途テスト）"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "人工知能",
                "correct_reading": "じんこうちのう",
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
        assert data["article_id"] is None
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

    def test_create_empty_body_422(self, client):
        """空のJSONボディは 422"""
        resp = client.post("/reports/misreading", json={})
        assert resp.status_code == 422

    def test_create_correct_reading_too_long_422(self, client):
        """correct_reading が最大長を超える場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={"target_text": "テスト", "correct_reading": "あ" * 501},
        )
        assert resp.status_code == 422

    def test_create_notes_too_long_422(self, client):
        """notes が最大長を超える場合は 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "notes": "補足" * 1001,
            },
        )
        assert resp.status_code == 422

    def test_create_with_emoji_special_chars(self, client):
        """絵文字・特殊文字を含む本文を保持して登録できる"""
        target_text = "AI 🎧 <読み間違い> & テスト"
        resp = client.post(
            "/reports/misreading",
            json={"target_text": target_text, "correct_reading": "えーあい"},
        )
        assert resp.status_code == 201
        assert resp.json()["target_text"] == target_text

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

    def test_negative_article_id_422(self, client):
        """article_id が負の値の場合は 422（Pydantic ge=1 で拒否）"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "article_id": -1,
            },
        )
        assert resp.status_code == 422

    def test_zero_article_id_422(self, client):
        """article_id が 0 の場合は 422（Pydantic ge=1 で拒否）"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "article_id": 0,
            },
        )
        assert resp.status_code == 422

    def test_nonexistent_article_id_404(self, client):
        """存在しない article_id の場合は 404"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "article_id": 99999,
            },
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Referenced article not found"

    def test_valid_article_id_success(self, client):
        """存在する article_id と共に登録できる"""
        article_id = _seed_article(client, "article_idテスト")
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "記事IDあり",
                "correct_reading": "きじあいであり",
                "article_id": article_id,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["article_id"] == article_id

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

    def test_create_missing_required_fields_422(self, client):
        """必須フィールドなし（空JSON）は 422"""
        resp = client.post("/reports/misreading", json={})
        assert resp.status_code == 422

    def test_create_truly_empty_body_422(self, client):
        """HTTPボディ自体が空の場合は 422"""
        resp = client.post(
            "/reports/misreading",
            headers={"Content-Type": "application/json"},
            data=b"",
        )
        assert resp.status_code == 422

    def test_create_correct_reading_too_long_422(self, client):
        """correct_reading が500文字を超えると 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "あ" * 501,
            },
        )
        assert resp.status_code == 422

    def test_create_correct_reading_max_length_201(self, client):
        """correct_reading が500文字ちょうどで登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "あ" * 500,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["correct_reading"]) == 500

    def test_create_notes_too_long_422(self, client):
        """notes が2000文字を超えると 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "notes": "x" * 2001,
            },
        )
        assert resp.status_code == 422

    def test_create_notes_max_length_201(self, client):
        """notes が2000文字ちょうどで登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "てすと",
                "notes": "x" * 2000,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["notes"]) == 2000

    def test_create_target_text_max_length_201(self, client):
        """target_text が2000文字ちょうどで登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "a" * 2000,
                "correct_reading": "てすと",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["target_text"]) == 2000

    def test_create_whitespace_only_target_text_422(self, client):
        """空白のみの target_text は 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "   ",
                "correct_reading": "てすと",
            },
        )
        assert resp.status_code == 422

    def test_create_whitespace_only_correct_reading_422(self, client):
        """空白のみの correct_reading は 422"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト",
                "correct_reading": "   ",
            },
        )
        assert resp.status_code == 422

    def test_create_with_emoji_special_chars(self, client):
        """絵文字や特殊文字を含むテキストが登録できる"""
        resp = client.post(
            "/reports/misreading",
            json={
                "target_text": "テスト🔥💯 & < > ' \"",
                "correct_reading": "てすと えもじ",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "🔥💯 & < > ' \"" in data["target_text"]


class TestMisreadingReportMigration:
    """旧スキーマDB（misreading_reports 未作成）からの起動テスト"""

    def _old_schema_db_without_reports(self, tmp_path):
        """misreading_reports テーブルがない旧スキーマDBを作成する"""
        from pathlib import Path
        db_file = tmp_path / "test.db"
        ep_dir = tmp_path / "episodes"
        ep_dir.mkdir(exist_ok=True)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        schema_path = str(Path(__file__).parent.parent / "app" / "db" / "schema.sql")
        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute("DROP TABLE misreading_reports")
        conn.commit()
        conn.close()
        return db_file, ep_dir

    def test_migration_creates_table_and_preserves_data(self, tmp_path, monkeypatch):
        """既存DB起動時にテーブルが作成され、既存データが保持される"""
        db_file, ep_dir = self._old_schema_db_without_reports(tmp_path)

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("EPISODES_DIR", str(ep_dir))
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")

        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "misreading_reports" in tables, "マイグレーション後にテーブルが存在する"

        existing_count = conn.execute(
            "SELECT COUNT(*) FROM dictionary_entries"
        ).fetchone()[0]
        assert existing_count > 0, "既存の辞書データが保持されている"
        conn.close()

    def test_migration_through_client_with_old_schema(self, tmp_path, monkeypatch):
        """旧スキーマDB起動後、報告の登録と取得が正常に動作する"""
        db_file, ep_dir = self._old_schema_db_without_reports(tmp_path)

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("EPISODES_DIR", str(ep_dir))
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")

        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)

        resp = client.post(
            "/reports/misreading",
            json={"target_text": "移行後テスト", "correct_reading": "いこうごてすと"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_text"] == "移行後テスト"

        # 起動を繰り返しても問題ないこと（二重実行の冪等性）
        importlib.reload(main_mod)
        client2 = TestClient(app)
        resp2 = client2.post(
            "/reports/misreading",
            json={"target_text": "二回目起動", "correct_reading": "にかいめきどう"},
        )
        assert resp2.status_code == 201
