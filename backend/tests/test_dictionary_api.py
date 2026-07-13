"""Tests for dictionary entries CRUD API with UNIQUE(surface, reading) constraint."""

import pytest
import sqlite3
from pathlib import Path


class TestCreateDictionaryEntry:
    """POST /admin/dictionary のテスト"""

    def test_create_entry(self, client):
        resp = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["word"] == "テスト"
        assert data["reading"] == "てすと"
        assert data["status"] == "active"

    def test_create_duplicate_surface_reading(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        resp = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Dictionary entry already exists"

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


class TestListDictionaryEntries:
    """GET /admin/dictionary のテスト"""

    def test_list_empty(self, client):
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


class TestUpdateDictionaryEntry:
    """PUT /admin/dictionary/{id} のテスト"""

    def test_update_entry(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.put(
            f"/admin/dictionary/{created['id']}",
            json={"word": "更新", "reading": "こうしん", "category": "general"},
        )
        assert resp.status_code == 200
        assert resp.json()["word"] == "更新"
        assert resp.json()["reading"] == "こうしん"

    def test_update_to_existing_word_reading(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "既存", "reading": "きそん", "category": "general"},
        )
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.put(
            f"/admin/dictionary/{created['id']}",
            json={"word": "既存", "reading": "きそん", "category": "general"},
        )
        assert resp.status_code == 409

    def test_update_404(self, client):
        resp = client.put(
            "/admin/dictionary/99999",
            json={"word": "なし", "reading": "なし", "category": "general"},
        )
        assert resp.status_code == 404


class TestGetDictionaryEntry:
    """GET /admin/dictionary/{id} のテスト"""

    def test_get_entry(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.get(f"/admin/dictionary/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["word"] == "テスト"

    def test_get_404(self, client):
        resp = client.get("/admin/dictionary/99999")
        assert resp.status_code == 404


class TestDictionaryEntryStatus:
    """PATCH /admin/dictionary/{id}/status のテスト"""

    def test_toggle_status(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()
        assert created["status"] == "active"

        resp = client.patch(
            f"/admin/dictionary/{created['id']}/status",
            json={"status": "inactive"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

        resp = client.patch(
            f"/admin/dictionary/{created['id']}/status",
            json={"status": "active"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


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
        from app import config as cfg_mod
        if hasattr(cfg_mod.get_settings, "cache_clear"):
            cfg_mod.get_settings.cache_clear()

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
