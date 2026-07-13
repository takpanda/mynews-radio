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

    def test_empty_db_returns_text_unchanged(self, test_env):
        """DBが空の場合、入力テキストがそのまま返される"""
        from app.services.replacement_table import apply_replacements

        result = apply_replacements("Google announced a new product")
        assert result == "Google announced a new product"

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


_SEED_ENTRIES: list[tuple[str, str]] = [
    ("Google", "グーグル"),
    ("Microsoft", "マイクロソフト"),
    ("Amazon", "アマゾン"),
    ("Apple", "アップル"),
    ("Meta", "メタ"),
    ("Google Cloud", "グーグル クラウド"),
    ("AWS", "エースシーリー"),
    ("Azure", "アジュール"),
    ("GitHub", "ギットハブ"),
    ("GitLab", "ギットラブ"),
    ("Docker", "ドッカー"),
    ("Kubernetes", "キューベルネティース"),
    ("Prometheus", "プロミーテゥス"),
    ("Grafana", "グラファナ"),
    ("Ansible", "アンシホル"),
    ("Terraform", "テラフォーム"),
    ("PyTorch", "パイトッチ"),
    ("TensorFlow", "テンソーフロー"),
]


class TestSeedDataReplacements:
    """元 REPLACEMENT_TABLE と同じ seed データで置換結果が一致することの回帰テスト"""

    def _seed_all(self):
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            for surface, reading in _SEED_ENTRIES:
                conn.execute(
                    "INSERT INTO dictionary_entries(surface, reading, is_active) VALUES (?, ?, 1)",
                    (surface, reading),
                )
            conn.commit()

    def test_seed_data_aws(self, test_env):
        self._seed_all()
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("AWS announced new services")
        assert "エースシーリー" in result

    def test_seed_data_google(self, test_env):
        self._seed_all()
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Google and Google Cloud are expanding")
        assert "グーグル" in result
        assert "グーグル クラウド" in result

    def test_seed_data_microsoft(self, test_env):
        self._seed_all()
        from app.services.replacement_table import apply_replacements
        result = apply_replacements("Microsoft released a new Windows update")
        assert "マイクロソフト" in result

    def test_seed_data_multi_replacements(self, test_env):
        self._seed_all()
        from app.services.replacement_table import apply_replacements
        text = "Google uses AWS and Docker for cloud infrastructure"
        result = apply_replacements(text)
        assert "グーグル" in result
        assert "エースシーリー" in result
        assert "ドッカー" in result


class TestSynthesizeEpisodeNullText:
    """synthesize_episode が text: null を含む script.json を空文字として処理するテスト"""

    def test_null_text_is_handled_as_empty_string(self, tmp_path, monkeypatch):
        import json

        from app.batch.synthesize_voicevox import synthesize_episode

        # script.json に text: null を含む行を作成
        lines = [
            {"text": "正常なテキスト", "section": "news", "speaker": "male"},
            {"text": None, "section": "news", "speaker": "female"},
            {"text": "後続のテキスト", "section": "news", "speaker": "male"},
        ]
        script = {"title": "テスト", "lines": lines}
        ep_dir = tmp_path / "ep_test"
        ep_dir.mkdir()
        script_path = ep_dir / "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f)

        # VoicevoxClient.synthesize_line をモック（WAVファイルを作成）
        def mock_synthesize_line(self, text, speaker, output_path, delivery="neutral"):
            with open(output_path, "w") as f:
                f.write("dummy")
            return True

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            mock_synthesize_line,
        )

        result = synthesize_episode(str(ep_dir))

        assert result == 3, "全3行が合成成功すること"

        # 書き戻された script.json を確認
        with open(script_path, "r", encoding="utf-8") as f:
            updated = json.load(f)

        # null だった行は display_text="" / spoken_text=""
        null_line = updated["lines"][1]
        assert null_line["display_text"] == ""
        assert null_line["spoken_text"] == ""
        assert null_line["wav_file"] == "002.wav"

        # 正常行はそのまま
        normal_line = updated["lines"][0]
        assert normal_line["display_text"] == "正常なテキスト"
        assert normal_line["spoken_text"] != ""

        end_line = updated["lines"][2]
        assert end_line["display_text"] == "後続のテキスト"
        assert end_line["wav_file"] == "003.wav"
