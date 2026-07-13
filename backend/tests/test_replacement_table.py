import sqlite3

import pytest


def _insert_entry(conn: sqlite3.Connection, surface: str, reading: str, is_active: int = 1):
    conn.execute(
        "INSERT INTO dictionary_entries(surface, reading, is_active) VALUES (?, ?, ?)",
        (surface, reading, is_active),
    )
    conn.commit()


class TestApplyReplacements:
    def test_all_disabled_returns_text_unchanged(self, test_env):
        """DBに1件エントリを登録→無効化→ハードコード表と同じ表層形でapply_replacementsを呼び出し、置換されない"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "Google", "グーグル", is_active=0)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google announced a new product")
        assert result == "Google announced a new product"

    def test_all_disabled_multi_entries(self, test_env):
        """複数のエントリが全件無効の場合、置換されない"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "Google", "グーグル", is_active=0)
            _insert_entry(conn, "AWS", "エー・ダブリュー・エス", is_active=0)

        from app.services.replacement_table import apply_replacements

        text = "Google and AWS are leading cloud providers"
        result = apply_replacements(text)
        assert result == text

    def test_empty_db_falls_back_to_static_table(self, test_env):
        """DBが空の場合、REPLACEMENT_TABLEの値で置換される"""
        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google announced a new product")
        assert result == "グーグル announced a new product"

    def test_mixed_enabled_disabled(self, test_env):
        """有効・無効が混在する場合、有効エントリのみ適用される"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "Google", "グーグル", is_active=1)
            _insert_entry(conn, "Microsoft", "マクロソフト", is_active=0)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google and Microsoft are tech companies")
        assert "グーグル" in result
        assert "Microsoft" in result
        assert "マクロソフト" not in result

    def test_active_db_entries_used(self, test_env):
        """有効エントリのみで置換されることを確認"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "Google", "グーグる", is_active=1)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google is a search engine")
        assert "グーグる" in result

    def test_regex_metachar_c_plus_plus(self, test_env):
        """re.escape メタ文字（C++）が正しく置換される"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "C++", "シープラスプラス", is_active=1)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("C++ is a language")
        assert "シープラスプラス" in result
        assert "C++" not in result.replace("シープラスプラス", "")

    def test_regex_metachar_dot_js(self, test_env):
        """re.escape メタ文字（node.js）が正しく置換される"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "node.js", "ノードジェイエス", is_active=1)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Use node.js for backend")
        assert "ノードジェイエス" in result

    def test_regex_metachar_brackets(self, test_env):
        """re.escape メタ文字（[test]）が正しく置換される"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "[test]", "テスト", is_active=1)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("This is [test] data")
        assert "テスト" in result

    def test_regex_metachar_mixed_with_normal(self, test_env):
        """メタ文字を含むエントリと通常エントリが混在する場合、両方正しく置換される"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            _insert_entry(conn, "C++", "シープラスプラス", is_active=1)
            _insert_entry(conn, "Google", "グーグル", is_active=1)

        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google uses C++ for performance")
        assert "グーグル" in result
        assert "シープラスプラス" in result
