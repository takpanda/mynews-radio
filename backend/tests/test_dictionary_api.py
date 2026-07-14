"""Tests for dictionary entry management API."""

import json

import pytest
import sqlite3
from pathlib import Path


def _seed_entry(client, word="TestWord", reading="テストワード", category="test", notes=""):
    """Helper: create a dictionary entry and return the response JSON."""
    resp = client.post(
        "/admin/dictionary",
        json={"word": word, "reading": reading, "category": category, "notes": notes},
    )
    return resp


class TestDictionaryCreate:
    """POST /admin/dictionary のテスト"""

    def test_create_success(self, client):
        resp = _seed_entry(client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["word"] == "TestWord"
        assert data["reading"] == "テストワード"
        assert data["category"] == "test"
        assert data["status"] == "active"
        assert "id" in data
        assert "updated_at" in data

    def test_create_duplicate_word_reading(self, client):
        _seed_entry(client, word="Duplicate", reading="デュプリケート")
        resp = _seed_entry(client, word="Duplicate", reading="デュプリケート")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Dictionary entry already exists"

    def test_diff_word_same_reading_ok(self, client):
        _seed_entry(client, word="First", reading="同じ")
        resp = _seed_entry(client, word="Second", reading="同じ")
        assert resp.status_code == 201

    def test_create_missing_fields(self, client):
        resp = client.post("/admin/dictionary", json={"word": "test"})
        assert resp.status_code == 422

    def test_create_word_too_long(self, client):
        resp = client.post(
            "/admin/dictionary",
            json={"word": "a" * 101, "reading": "test", "category": "test"},
        )
        assert resp.status_code == 422

    def test_create_reading_too_long(self, client):
        resp = client.post(
            "/admin/dictionary",
            json={
                "word": "test",
                "reading": "あ" * 201,
                "category": "test",
            },
        )
        assert resp.status_code == 422

    def test_create_with_notes(self, client):
        resp = _seed_entry(
            client, word="WithNotes", reading="ウィズノート", notes="備考テキスト"
        )
        assert resp.status_code == 201
        assert resp.json()["notes"] == "備考テキスト"

    def test_create_same_word_different_reading(self, client):
        """同じ word で reading が異なる場合は別エントリとして登録できる"""
        resp1 = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "とうきょう", "category": "general"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "トウキョウ", "category": "general"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["word"] == "東京"
        assert resp2.json()["reading"] == "トウキョウ"


class TestDictionaryList:
    """GET /admin/dictionary のテスト"""

    def _create_many(self, client, n: int = 5):
        ids = []
        for i in range(n):
            resp = _seed_entry(
                client, word=f"Word{i}", reading=f"リーディング{i}", category="test"
            )
            ids.append(resp.json()["id"])
        return ids

    def test_list_no_params(self, client):
        self._create_many(client, 3)
        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_list_paginated(self, client):
        self._create_many(client, 10)
        resp = client.get("/admin/dictionary?limit=3&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data
        assert "has_next" in data
        assert "stats" in data
        assert len(data["items"]) == 3
        assert data["total"] == 10
        assert data["has_next"] is True

    def test_list_has_stats(self, client):
        self._create_many(client, 5)
        resp = client.get("/admin/dictionary?limit=3&offset=0")
        data = resp.json()
        stats = data["stats"]
        assert stats["total"] == 5
        assert stats["active"] == 5
        assert stats["inactive"] == 0

    def test_list_last_page(self, client):
        self._create_many(client, 10)
        resp = client.get("/admin/dictionary?limit=3&offset=9")
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["has_next"] is False

    def test_list_empty(self, client):
        resp = client.get("/admin/dictionary?limit=5&offset=100")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 0
        assert data["total"] == 0
        assert data["has_next"] is False

    def test_list_empty_no_params(self, client):
        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_entries(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "とうきょう", "category": "place"},
        )
        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        words = {e["word"] for e in data}
        assert words == {"テスト", "東京"}

    def test_list_search(self, client):
        _seed_entry(client, word="GoogleCloud", reading="グーグルクラウド")
        _seed_entry(client, word="AzureCloud", reading="アジュールクラウド")
        resp = client.get("/admin/dictionary?search=Google")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["word"] == "GoogleCloud"

    def test_list_category_filter(self, client):
        _seed_entry(client, word="A", reading="エー", category="cat1")
        _seed_entry(client, word="B", reading="ビー", category="cat2")
        resp = client.get("/admin/dictionary?category=cat1")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["word"] == "A"

    def test_list_status_filter_active(self, client):
        _seed_entry(client, word="Active", reading="アクティブ")
        resp = client.get("/admin/dictionary?status=active")
        data = resp.json()
        assert len(data) == 1

    def test_list_status_filter_inactive(self, client):
        _seed_entry(client, word="Active", reading="アクティブ")
        client.patch(
            "/admin/dictionary/1/status",
            json={"status": "inactive"},
        )
        resp = client.get("/admin/dictionary?status=inactive")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "inactive"

    def test_list_combined_filters(self, client):
        _seed_entry(client, word="Alpha", reading="アルファ", category="tech")
        _seed_entry(client, word="Alpha2", reading="アルファ2", category="news")
        resp = client.get("/admin/dictionary?search=Alpha&category=tech")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["word"] == "Alpha"

    def test_limit_zero_rejected(self, client):
        resp = client.get("/admin/dictionary?limit=0")
        assert resp.status_code == 422

    def test_limit_negative_rejected(self, client):
        resp = client.get("/admin/dictionary?limit=-1")
        assert resp.status_code == 422

    def test_offset_negative_rejected(self, client):
        resp = client.get("/admin/dictionary?limit=5&offset=-1")
        assert resp.status_code == 422

    def test_list_status_invalid_value(self, client):
        resp = client.get("/admin/dictionary?status=invalid")
        assert resp.status_code == 422


class TestDictionaryGet:
    """GET /admin/dictionary/{id} のテスト"""

    def test_get_success(self, client):
        created = _seed_entry(client).json()
        resp = client.get(f"/admin/dictionary/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_404(self, client):
        resp = client.get("/admin/dictionary/99999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Dictionary entry not found"


class TestDictionaryUpdate:
    """PUT /admin/dictionary/{id} のテスト"""

    def test_update_success(self, client):
        created = _seed_entry(client, word="Original").json()
        eid = created["id"]
        resp = client.put(
            f"/admin/dictionary/{eid}",
            json={"word": "Updated", "reading": "アップデート", "category": "updated", "notes": "updated note"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["word"] == "Updated"
        assert data["reading"] == "アップデート"
        assert data["category"] == "updated"
        assert data["notes"] == "updated note"

    def test_update_404(self, client):
        resp = client.put(
            "/admin/dictionary/99999",
            json={"word": "Nope", "reading": "ノー", "category": "x", "notes": ""},
        )
        assert resp.status_code == 404

    def test_update_conflict(self, client):
        _seed_entry(client, word="Existing", reading="エクシスティング")
        created = _seed_entry(client, word="Other", reading="アザー").json()
        resp = client.put(
            f"/admin/dictionary/{created['id']}",
            json={
                "word": "Existing",
                "reading": "エクシスティング",
                "category": "x",
                "notes": "",
            },
        )
        assert resp.status_code == 409


class TestDictionaryStatusToggle:
    """PATCH /admin/dictionary/{id}/status のテスト"""

    def test_toggle_to_inactive(self, client):
        created = _seed_entry(client).json()
        eid = created["id"]
        resp = client.patch(f"/admin/dictionary/{eid}/status", json={"status": "inactive"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

    def test_toggle_back_to_active(self, client):
        created = _seed_entry(client).json()
        eid = created["id"]
        client.patch(f"/admin/dictionary/{eid}/status", json={"status": "inactive"})
        resp = client.patch(f"/admin/dictionary/{eid}/status", json={"status": "active"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_toggle_idempotent(self, client):
        created = _seed_entry(client).json()
        eid = created["id"]
        resp = client.patch(f"/admin/dictionary/{eid}/status", json={"status": "active"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_toggle_404(self, client):
        resp = client.patch("/admin/dictionary/99999/status", json={"status": "inactive"})
        assert resp.status_code == 404

    def test_toggle_invalid_status(self, client):
        created = _seed_entry(client).json()
        eid = created["id"]
        resp = client.patch(
            f"/admin/dictionary/{eid}/status", json={"status": "invalid"}
        )
        assert resp.status_code == 422


class TestDictionaryAuth:
    """認証周りのテスト"""

    def test_auth_required(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-secret-key")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.get("/admin/dictionary")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or missing API key"

    def test_auth_invalid_key(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-secret-key")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.get(
            "/admin/dictionary",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_auth_with_valid_key(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-secret-key")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.get(
            "/admin/dictionary",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200

    def test_no_auth_when_api_key_not_set(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "")
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200


class TestReplacementTableActiveFilter:
    """apply_replacements() が is_active=1 のエントリのみ使用することのテスト"""

    def test_active_entries_used(self, client):
        """有効な辞書エントリが apply_replacements で使用される"""
        _seed_entry(client, word="TestWord", reading="テストワード")
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Hello TestWord World")
        assert "テストワード" in result

    def test_inactive_entries_excluded(self, client):
        """無効な辞書エントリが apply_replacements で除外される"""
        _seed_entry(client, word="Excluded", reading="ムシ")
        client.patch("/admin/dictionary/1/status", json={"status": "inactive"})
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Hello Excluded World")
        assert "ムシ" not in result

    def test_fallback_to_hardcoded(self, client):
        """DB が空の場合、REPLACEMENT_TABLE がフォールバックとして使用される"""
        from app.db.connection import get_db_connection
        with get_db_connection() as c:
            c.execute("DELETE FROM dictionary_entries")
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Google is testing")
        assert "グーグル" in result

    def test_reactivated_entries_used(self, client):
        """無効→再有効化したエントリが apply_replacements で再び使用される"""
        _seed_entry(client, word="Reactivate", reading="リアクティベート")
        client.patch("/admin/dictionary/1/status", json={"status": "inactive"})
        client.patch("/admin/dictionary/1/status", json={"status": "active"})
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Test Reactivate Now")
        assert "リアクティベート" in result

    def test_all_disabled_returns_text_unchanged(self, client):
        """全エントリが無効 (is_active=0) の場合、入力テキストがそのまま返される"""
        _seed_entry(client, word="Google", reading="グーグル")
        _seed_entry(client, word="AWS", reading="エーエスシーリリー")
        client.patch("/admin/dictionary/1/status", json={"status": "inactive"})
        client.patch("/admin/dictionary/2/status", json={"status": "inactive"})
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Google and AWS are testing")
        assert "グーグル" not in result
        assert "エーエスシーリリー" not in result
        assert result == "Google and AWS are testing"


class TestExistingEpisodeSpokenText:
    """既存エピソードの spoken_text が辞書変更後も変わらないことの確認"""

    def test_spoken_text_preserved_after_dictionary_change(self, client, tmp_path):
        """辞書エントリを変更しても、既存 script.json の spoken_text は変わらない"""
        _seed_entry(client, word="Google", reading="グーグル")

        episode_dir = tmp_path / "episodes" / "1"
        episode_dir.mkdir(parents=True)
        script = {
            "title": "Test Episode",
            "lines": [
                {
                    "text": "Google announced new AI",
                    "display_text": "Google announced new AI",
                    "spoken_text": "グーグル announced new AI",
                    "speaker": "male",
                    "section": "news",
                },
                {
                    "text": "AWS is also competing",
                    "display_text": "AWS is also competing",
                    "spoken_text": "エーエスシーリリー is also competing",
                    "speaker": "male",
                    "section": "news",
                },
            ],
        }
        script_path = episode_dir / "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)

        expected = dict(script)

        client.patch("/admin/dictionary/1/status", json={"status": "inactive"})
        _seed_entry(client, word="AWS", reading="アマゾンウェブサービス")

        with open(script_path, "r", encoding="utf-8") as f:
            actual = json.load(f)

        assert actual == expected
        assert actual["lines"][0]["spoken_text"] == "グーグル announced new AI"
        assert actual["lines"][1]["spoken_text"] == "エーエスシーリリー is also competing"


def _old_schema_sql():
    """UNIQUE(surface) の旧スキーマSQLを返す。"""
    return """
    CREATE TABLE IF NOT EXISTS dictionary_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surface TEXT NOT NULL UNIQUE,
        reading TEXT NOT NULL,
        category TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """


class TestMigrationFromOldSchema:
    """UNIQUE(surface) → UNIQUE(surface, reading) マイグレーションのテスト"""

    def _create_old_schema_db(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(_old_schema_sql())
        conn.executescript(
            "ALTER TABLE dictionary_entries ADD COLUMN notes TEXT DEFAULT ''"
        )
        conn.commit()
        conn.close()

    def _run_migration_on_db(self, db_path):
        """実際の migrate_dictionary_constraint を実行する。"""
        from app.db.migration import migrate_dictionary_constraint
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = migrate_dictionary_constraint(conn)
        conn.commit()
        conn.close()
        return result

    def _assert_migrated(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dictionary_entries' AND name LIKE 'sqlite_autoindex_dictionary_entries%'"
        ).fetchone()
        assert idx is not None, "複合UNIQUEの自動インデックスが見つかりません"
        cols = conn.execute(
            f"PRAGMA index_info('{idx['name']}')"
        ).fetchall()
        assert len(cols) == 2, f"複合UNIQUEは2カラム必要: {[c['name'] for c in cols]}"
        assert cols[0]['name'] == 'surface'
        assert cols[1]['name'] == 'reading'
        conn.close()

    def test_migration_preserves_data(self, tmp_path):
        """旧スキーマのデータがマイグレーション後も保持される"""
        db_path = tmp_path / "test_migrate.db"
        self._create_old_schema_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("テスト", "てすと", "general"),
        )
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("東京", "とうきょう", "place"),
        )
        conn.commit()
        conn.close()

        result = self._run_migration_on_db(db_path)
        assert result is True, "1回目のマイグレーションが実行されませんでした"
        self._assert_migrated(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT surface AS word, reading, category FROM dictionary_entries ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]['word'] == "テスト"
        assert rows[1]['word'] == "東京"

        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("東京", "トウキョウ", "place"),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
                ("東京", "トウキョウ", "place"),
            )
            conn.commit()
        conn.close()

    def test_migration_idempotent(self, tmp_path):
        """2回目の migrate_dictionary_constraint は何も変更しない"""
        db_path = tmp_path / "test_idempotent.db"
        self._create_old_schema_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("テスト", "てすと", "general"),
        )
        conn.commit()
        conn.close()

        result1 = self._run_migration_on_db(db_path)
        assert result1 is True, "1回目のマイグレーションが実行されませんでした"
        self._assert_migrated(db_path)

        ids_after_first = []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT id, surface FROM dictionary_entries").fetchall():
            ids_after_first.append((r['id'], r['surface']))
        conn.close()

        result2 = self._run_migration_on_db(db_path)
        assert result2 is False, "2回目のマイグレーションは実行されるべきではありません"
        self._assert_migrated(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        ids_after_second = []
        for r in conn.execute("SELECT id, surface FROM dictionary_entries").fetchall():
            ids_after_second.append((r['id'], r['surface']))
        conn.close()

        assert ids_after_first == ids_after_second

    def test_old_schema_detect_constraint(self, tmp_path):
        """旧スキーマ UNIQUE(surface) が正しく検出される"""
        db_path = tmp_path / "test_detect_old.db"
        self._create_old_schema_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dictionary_entries' AND name LIKE 'sqlite_autoindex_dictionary_entries%'"
        ).fetchone()
        assert idx is not None
        cols = conn.execute(f"PRAGMA index_info('{idx['name']}')").fetchall()
        assert len(cols) == 1
        assert cols[0]['name'] == 'surface'
        conn.close()

    def test_migrated_db_rejects_old_surface_only_duplicate(self, tmp_path):
        """移行後DBで旧制約 (surface単独の重複) を許容してしまうバグがない"""
        db_path = tmp_path / "test_reject_old_dup.db"
        self._create_old_schema_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("東京", "とうきょう", "place"),
        )
        conn.commit()
        conn.close()

        self._run_migration_on_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("東京", "トウキョウ", "place"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
                ("東京", "トウキョウ", "place"),
            )
            conn.commit()
        conn.close()

    def test_migration_through_client_with_old_schema(self, tmp_path, monkeypatch):
        """旧スキーマDBでアプリを起動したとき、マイグレーション後に同表記別読みが登録でき、
        かつ2回目のアプリ起動ではテーブル再構築が発生しないことを確認"""
        db_path = tmp_path / "test_client_migrate.db"
        self._create_old_schema_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, category) VALUES (?, ?, ?)",
            ("東京", "とうきょう", "place"),
        )
        conn.commit()
        conn.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)

        self._assert_migrated(db_path)

        resp = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "トウキョウ", "category": "place"},
        )
        assert resp.status_code == 201
        assert resp.json()["reading"] == "トウキョウ"

        resp = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "トウキョウ", "category": "place"},
        )
        assert resp.status_code == 409

        # 2回目のアプリ起動: テーブル再構築が発生しないことを確認
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        tables = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r['name'] for r in tables]
        assert 'dictionary_entries_old' not in table_names, \
            "2回目の起動で RENAME が発行されました"

        # スキーマが正しいことも確認
        self._assert_migrated(db_path)
        conn2.close()

        # 3回目の起動でも問題ないことを確認（migrate_dictionary_constraint を直接）
        result3 = self._run_migration_on_db(db_path)
        assert result3 is False, "3回目のマイグレーションは実行されるべきではありません"
