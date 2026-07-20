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
            content=b"",
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


class TestAdminMisreadingReportList:
    """GET /admin/reports/misreading のテスト（管理者認証付き一覧取得）"""

    def _set_api_key(self, monkeypatch, key="test-admin-key"):
        monkeypatch.setenv("API_KEY", key)
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

    def _seed_reports(self, client, count=3):
        """テストデータを投入し、登録されたIDリストを返す。"""
        ids = []
        for i in range(count):
            resp = client.post(
                "/reports/misreading",
                json={
                    "target_text": f"テスト文章{i}",
                    "correct_reading": f"てすとぶんしょう{i}",
                    "notes": f"メモ{i}",
                },
            )
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        return ids

    def test_list_with_auth(self, client, monkeypatch):
        """認証ありで全件取得できる"""
        self._set_api_key(monkeypatch)
        self._seed_reports(client, 3)

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_list_required_fields(self, client, monkeypatch):
        """レスポンスに必要なフィールドのみ含まれる"""
        self._set_api_key(monkeypatch)
        self._seed_reports(client, 1)

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        item = resp.json()[0]
        assert "id" in item
        assert "target_text" in item
        assert "correct_reading" in item
        assert "article_id" in item
        assert "notes" in item
        assert "created_at" in item
        assert "audio_generation_id" not in item
        assert "playback_position" not in item
        assert "app_version" not in item

    def test_list_ordered_by_created_at_id_desc(self, client, monkeypatch):
        """作成日時降順、同一時刻は id 降順で返ること"""
        self._set_api_key(monkeypatch)
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO misreading_reports (target_text, correct_reading, created_at) "
                "VALUES ('古い', 'ふるい', '2026-01-01 00:00:00')"
            )
            conn.execute(
                "INSERT INTO misreading_reports (target_text, correct_reading, created_at) "
                "VALUES ('中', 'なか', '2026-01-02 00:00:00')"
            )
            conn.execute(
                "INSERT INTO misreading_reports (target_text, correct_reading, created_at) "
                "VALUES ('新しい', 'あたらしい', '2026-01-03 00:00:00')"
            )
            conn.execute(
                "INSERT INTO misreading_reports (target_text, correct_reading, created_at) "
                "VALUES ('同秒B', 'どうびょうびー', '2026-01-03 00:00:00')"
            )
            conn.execute(
                "INSERT INTO misreading_reports (target_text, correct_reading, created_at) "
                "VALUES ('同秒A', 'どうびょうえー', '2026-01-03 00:00:00')"
            )

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        texts = [item["target_text"] for item in data]
        expected = ["同秒A", "同秒B", "新しい", "中", "古い"]
        assert texts == expected

    def test_list_empty(self, client, monkeypatch):
        """報告がない場合は空の配列を返す"""
        self._set_api_key(monkeypatch)

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_no_auth_header(self, client, monkeypatch):
        """Authorization ヘッダなしは 401"""
        self._set_api_key(monkeypatch)

        resp = client.get("/admin/reports/misreading")
        assert resp.status_code == 401
        assert "api key" in resp.json()["detail"].lower()

    def test_list_wrong_api_key(self, client, monkeypatch):
        """誤った Bearer トークンは 401"""
        self._set_api_key(monkeypatch)

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401
        assert "api key" in resp.json()["detail"].lower()

    def test_list_no_api_key_env(self, client, monkeypatch):
        """API_KEY 未設定時は 503 で拒否される"""
        monkeypatch.delenv("API_KEY", raising=False)
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.get("/admin/reports/misreading")
        assert resp.status_code == 503
        assert "api_key" in resp.json()["detail"].lower()


class TestAdminApproveMisreadingReport:
    """POST /admin/reports/misreading/{id}/approve のテスト"""

    def _set_api_key(self, monkeypatch, key="test-admin-key"):
        monkeypatch.setenv("API_KEY", key)
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

    def _create_report(self, client, target="テスト対象", reading="てすとたいしょう"):
        resp = client.post(
            "/reports/misreading",
            json={"target_text": target, "correct_reading": reading},
        )
        assert resp.status_code == 201
        return resp.json()

    def test_approve_success(self, client, monkeypatch):
        """未承認の報告を承認すると辞書エントリが作成され、approved 状態になる"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)
        report_id = report["id"]

        resp = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["report_id"] == report_id
        assert "dictionary_entry_id" in data

        entry_id = data["dictionary_entry_id"]

        resp2 = client.get(
            f"/admin/dictionary/{entry_id}",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp2.status_code == 200
        entry = resp2.json()
        assert entry["word"] == "テスト対象"
        assert entry["reading"] == "てすとたいしょう"
        assert entry["source_misreading_report_id"] == report_id

    def test_approve_with_article_id(self, client, monkeypatch):
        """article_id を持つ報告を承認すると、辞書エントリの source_misreading_report_id 経由で記事を追跡できる"""
        self._set_api_key(monkeypatch)
        article_id = _seed_article(client, "approveテスト")
        report = self._create_report(client, target="記事連携", reading="きじれんけい")
        report_id = report["id"]

        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE misreading_reports SET article_id = ? WHERE id = ?",
                (article_id, report_id),
            )

        resp = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        entry_id = resp.json()["dictionary_entry_id"]
        resp2 = client.get(
            f"/admin/dictionary/{entry_id}",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["source_misreading_report_id"] == report_id

    def test_approve_duplicate_original_skipped(self, client, monkeypatch):
        """同一 target_text が既に辞書にある場合は skip される"""
        self._set_api_key(monkeypatch)

        client.post(
            "/admin/dictionary",
            json={"word": "重複ワード", "reading": "ちょうふくわーど", "category": "test"},
            headers={"Authorization": "Bearer test-admin-key"},
        )

        report = self._create_report(client, target="重複ワード", reading="別のよみ")
        report_id = report["id"]

        resp = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert data["reason"] == "duplicate_original"
        assert data["report_id"] == report_id
        assert "existing_entry_id" in data

        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM dictionary_entries WHERE surface = '重複ワード'"
            ).fetchone()[0]
        assert count == 1, "重複する辞書エントリは作成されないこと"

    def test_approve_already_approved(self, client, monkeypatch):
        """既承認の報告を再承認すると already_approved を返し、辞書エントリは追加作成されない"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)
        report_id = report["id"]

        resp1 = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "approved"

        resp2 = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "already_approved"
        assert data2["dictionary_entry_id"] == resp1.json()["dictionary_entry_id"]

        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM dictionary_entries WHERE surface = 'テスト対象'"
            ).fetchone()[0]
            assert count == 1, "再承認で辞書エントリが追加作成されないこと"

            count2 = conn.execute(
                "SELECT COUNT(*) FROM misreading_reports WHERE id = ? AND approved = 1",
                (report_id,),
            ).fetchone()[0]
            assert count2 == 1

    def test_approve_not_found(self, client, monkeypatch):
        """存在しない報告IDは 404"""
        self._set_api_key(monkeypatch)

        resp = client.post(
            "/admin/reports/misreading/99999/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Report not found"

    def test_approve_no_auth_header(self, client, monkeypatch):
        """Authorization ヘッダなしは 401"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)
        report_id = report["id"]

        resp = client.post(f"/admin/reports/misreading/{report_id}/approve")
        assert resp.status_code == 401

    def test_approve_wrong_api_key(self, client, monkeypatch):
        """誤った Bearer トークンは 401"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)
        report_id = report["id"]

        resp = client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_approve_no_api_key_env(self, client, monkeypatch):
        """API_KEY 未設定時は 503 で拒否される"""
        monkeypatch.delenv("API_KEY", raising=False)
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        report = self._create_report(client)
        report_id = report["id"]

        resp = client.post(f"/admin/reports/misreading/{report_id}/approve")
        assert resp.status_code == 503

    def test_list_shows_approved_status_after_approve(self, client, monkeypatch):
        """承認後に一覧取得で approved 状態が確認できる"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)
        report_id = report["id"]

        client.post(
            f"/admin/reports/misreading/{report_id}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        items = resp.json()
        approved = [i for i in items if i["id"] == report_id]
        assert len(approved) == 1
        assert approved[0]["approved"] is True
        assert approved[0]["approved_dictionary_entry_id"] is not None
        assert approved[0]["approved_at"] is not None

    def test_list_shows_not_approved_before_approve(self, client, monkeypatch):
        """承認前の一覧で approved が false である"""
        self._set_api_key(monkeypatch)
        report = self._create_report(client)

        resp = client.get(
            "/admin/reports/misreading",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        items = resp.json()
        target = [i for i in items if i["id"] == report["id"]]
        assert len(target) == 1
        assert target[0]["approved"] is False
        assert target[0]["approved_at"] is None
        assert target[0]["approved_dictionary_entry_id"] is None

    def test_concurrent_approve_one_already_approved(self, client, monkeypatch):
        """並行して2回承認リクエストを送ると、1回目が approved、2回目が already_approved になる"""
        import concurrent.futures
        import threading

        self._set_api_key(monkeypatch)
        report = self._create_report(client, target="並行テスト", reading="へいこうてすと")
        report_id = report["id"]
        headers = {"Authorization": "Bearer test-admin-key"}
        url = f"/admin/reports/misreading/{report_id}/approve"

        results = []

        def _approve():
            resp = client.post(url, headers=headers)
            return resp.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_approve)
            f2 = executor.submit(_approve)
            results.append(f1.result())
            results.append(f2.result())

        statuses = [r["status"] for r in results]
        assert "approved" in statuses
        assert "already_approved" in statuses

        approved_result = next(r for r in results if r["status"] == "approved")
        already_result = next(r for r in results if r["status"] == "already_approved")

        assert already_result["dictionary_entry_id"] == approved_result["dictionary_entry_id"]


class TestMigrationFromOldColumns:
    """旧カラム構成（approved / source_misreading_report_id なし）からのマイグレーション回帰テスト"""

    def _old_schema_sql(self):
        """新カラムを持たない旧スキーマSQLを返す。"""
        return """
        CREATE TABLE IF NOT EXISTS misreading_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_text TEXT NOT NULL,
            correct_reading TEXT NOT NULL,
            article_id INTEGER,
            audio_generation_id TEXT,
            playback_position REAL,
            notes TEXT DEFAULT '',
            app_version TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS dictionary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            surface TEXT NOT NULL,
            reading TEXT NOT NULL,
            category TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(surface, reading)
        );
        """

    def _create_old_schema_db(self, tmp_path):
        """旧スキーマでDBを作成し、テストデータを投入する。"""
        import sqlite3
        from pathlib import Path

        db_file = tmp_path / "test_migration_old.db"
        ep_dir = tmp_path / "episodes"
        ep_dir.mkdir(exist_ok=True)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.executescript(self._old_schema_sql())

        conn.execute(
            "INSERT INTO dictionary_entries (surface, reading, category) VALUES (?, ?, ?)",
            ("既存辞書語", "きぞんじしょご", "test"),
        )
        conn.execute(
            "INSERT INTO dictionary_entries (surface, reading, category) VALUES (?, ?, ?)",
            ("マイグレーション", "まいぐれーしょん", "test"),
        )
        conn.execute(
            "INSERT INTO misreading_reports (target_text, correct_reading, notes) VALUES (?, ?, ?)",
            ("未承認報告", "みしょうにんほうこく", "migration test"),
        )
        conn.execute(
            "INSERT INTO misreading_reports (target_text, correct_reading, notes) VALUES (?, ?, ?)",
            ("対象外", "たいしょうがい", "existing data"),
        )
        conn.commit()
        conn.close()

        return db_file, ep_dir

    def _run_app_with_migrations(self, db_file, ep_dir, monkeypatch):
        """アプリを起動し、マイグレーションを実行する。"""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("EPISODES_DIR", str(ep_dir))
        monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")

        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        return main_mod

    def test_migration_adds_columns_and_preserves_data(self, tmp_path, monkeypatch):
        """旧スキーマDB起動後、新カラムが追加され既存データが保持される"""
        db_file, ep_dir = self._create_old_schema_db(tmp_path)
        self._run_app_with_migrations(db_file, ep_dir, monkeypatch)

        import sqlite3
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row

        misreading_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(misreading_reports)"
        ).fetchall()]
        assert "approved" in misreading_cols
        assert "approved_at" in misreading_cols
        assert "approved_dictionary_entry_id" in misreading_cols

        dict_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(dictionary_entries)"
        ).fetchall()]
        assert "source_misreading_report_id" in dict_cols

        dict_count = conn.execute("SELECT COUNT(*) FROM dictionary_entries").fetchone()[0]
        assert dict_count >= 2, "既存の辞書データが保持されている"

        report_count = conn.execute("SELECT COUNT(*) FROM misreading_reports").fetchone()[0]
        assert report_count >= 2, "既存の報告データが保持されている"

        row = conn.execute(
            "SELECT target_text, correct_reading, notes FROM misreading_reports WHERE target_text = '未承認報告'"
        ).fetchone()
        assert row is not None
        assert row["correct_reading"] == "みしょうにんほうこく"

        row = conn.execute(
            "SELECT surface, reading FROM dictionary_entries WHERE surface = '既存辞書語'"
        ).fetchone()
        assert row is not None
        assert row["reading"] == "きぞんじしょご"
        conn.close()

    def test_migration_idempotent_restart(self, tmp_path, monkeypatch):
        """再起動時にマイグレーションが二重実行されず、データが破損しない"""
        db_file, ep_dir = self._create_old_schema_db(tmp_path)

        self._run_app_with_migrations(db_file, ep_dir, monkeypatch)

        import sqlite3
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        ids_before = [
            dict(r) for r in conn.execute("SELECT id, surface FROM dictionary_entries").fetchall()
        ]
        reports_before = [
            dict(r) for r in conn.execute("SELECT id, target_text FROM misreading_reports").fetchall()
        ]
        conn.close()

        self._run_app_with_migrations(db_file, ep_dir, monkeypatch)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        ids_after = [
            dict(r) for r in conn.execute("SELECT id, surface FROM dictionary_entries").fetchall()
        ]
        reports_after = [
            dict(r) for r in conn.execute("SELECT id, target_text FROM misreading_reports").fetchall()
        ]

        assert ids_before == ids_after, "2回目の起動で辞書データが変わっていない"
        assert reports_before == reports_after, "2回目の起動で報告データが変わっていない"

        misreading_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(misreading_reports)"
        ).fetchall()]
        assert "approved" in misreading_cols
        conn.close()

    def test_migration_approve_after_migration(self, tmp_path, monkeypatch):
        """マイグレーション後、承認APIが正常に動作する"""
        db_file, ep_dir = self._create_old_schema_db(tmp_path)
        self._run_app_with_migrations(db_file, ep_dir, monkeypatch)

        monkeypatch.setenv("API_KEY", "test-admin-key")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)

        report = client.post(
            "/reports/misreading",
            json={"target_text": "移行後承認", "correct_reading": "いこうごしょうにん"},
        ).json()

        resp = client.post(
            f"/admin/reports/misreading/{report['id']}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        resp = client.post(
            f"/admin/reports/misreading/{report['id']}/approve",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_approved"

        dict_resp = client.get(
            f"/admin/dictionary/{resp.json()['dictionary_entry_id']}",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert dict_resp.status_code == 200
        assert dict_resp.json()["source_misreading_report_id"] == report["id"]
