"""VoicevoxClient.synthesize_line の kana_text 条件付き指定テスト"""
from unittest.mock import MagicMock, patch

import pytest


class TestSynthesizeLineKanaText:
    """synthesize_line が kana_text を条件付きで get_audio_query に渡すことを確認する"""

    def _make_client(self):
        from app.services.voicevox_client import VoicevoxClient
        client = VoicevoxClient("http://localhost:50021")
        client._client = MagicMock()
        return client

    def test_kana_text_none_default(self):
        """kana_text 未指定（既定 None）で get_audio_query の kana_text=None となること"""
        client = self._make_client()
        client.get_audio_query = MagicMock(return_value='{"kana": "エンジンの解析"}')
        client.synthesize = MagicMock(return_value=True)

        result = client.synthesize_line("通常テキスト", "male", "/tmp/test.wav")

        assert result is True
        client.get_audio_query.assert_called_once()
        _, kwargs = client.get_audio_query.call_args
        # kana_text が明示的に None で渡されていること
        assert "kana_text" in kwargs
        assert kwargs["kana_text"] is None

    def test_kana_text_explicitly_passed(self):
        """kana_text を明示指定すると get_audio_query にその値が渡ること"""
        client = self._make_client()
        client.get_audio_query = MagicMock(return_value='{"kana": "かながわ"}')
        client.synthesize = MagicMock(return_value=True)

        result = client.synthesize_line(
            "神奈川", "female", "/tmp/test.wav",
            kana_text="カナガワ",
        )

        assert result is True
        client.get_audio_query.assert_called_once()
        _, kwargs = client.get_audio_query.call_args
        assert kwargs["kana_text"] == "カナガワ"

    def test_kana_text_with_delivery(self):
        """kana_text 指定 + delivery パラメータが共存できること"""
        client = self._make_client()
        client.get_audio_query = MagicMock(return_value='{"kana": ""}')
        client.synthesize = MagicMock(return_value=True)

        result = client.synthesize_line(
            "強調テキスト", "male", "/tmp/test.wav",
            delivery="emphasis",
            kana_text="キョウチョウテキスト",
        )

        assert result is True
        client.get_audio_query.assert_called_once()
        _, kwargs = client.get_audio_query.call_args
        assert kwargs["kana_text"] == "キョウチョウテキスト"
        # query_params が delivery から導出されていること
        assert kwargs["query_params"] is not None

    def test_synthesize_line_failure_when_audio_query_none(self):
        """get_audio_query が None を返したら synthesize_line も False を返すこと"""
        client = self._make_client()
        client.get_audio_query = MagicMock(return_value=None)

        result = client.synthesize_line("失敗テスト", "male", "/tmp/test.wav")

        assert result is False


class TestSynthesizeVoicevoxKanaTextIntegration:
    """synthesize_voicevox.synthesize_episode における kana_text 条件付き指定の統合テスト"""

    def _insert_entry(self, conn, surface, reading, is_active=1):
        import sqlite3
        conn.execute(
            "INSERT INTO dictionary_entries(surface, reading, is_active) VALUES (?, ?, ?)",
            (surface, reading, is_active),
        )
        conn.commit()

    def _create_script(self, directory, lines):
        import json
        script = {"title": "テスト", "lines": lines}
        script_path = directory / "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f)

    def test_kana_text_not_passed_when_no_replacement(self, test_env, tmp_path, monkeypatch):
        """置換がない場合、kana_text が None で synthesize_line に渡されること"""
        from app.db.connection import get_db_connection

        # 有効な辞書エントリを登録（ただし該当テキストにはマッチしない）
        with get_db_connection() as conn:
            self._insert_entry(conn, "Google", "グーグル")

        # VoicevoxClient.synthesize_line をモックして kana_text の値を記録
        captured_kwargs = {}

        def mock_synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
            captured_kwargs["kana_text"] = kana_text
            with open(output_path, "w") as f:
                f.write("dummy")
            return True

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            mock_synthesize_line,
        )

        # 置換対象外のテキストでスクリプトを作成
        ep_dir = tmp_path / "ep_no_replace"
        ep_dir.mkdir()
        self._create_script(ep_dir, [
            {"text": "次にニュースです", "section": "news", "speaker": "male"},
        ])

        from app.batch.synthesize_voicevox import synthesize_episode
        result = synthesize_episode(str(ep_dir))

        assert result == 1
        assert captured_kwargs.get("kana_text") is None, \
            "置換なしの場合は kana_text=None で呼ばれるべき"

    def test_kana_text_passed_when_replacement_applied(self, test_env, tmp_path, monkeypatch):
        """置換があった場合、置換後テキストが kana_text として渡されること"""
        from app.db.connection import get_db_connection

        # 有効な辞書エントリを登録
        with get_db_connection() as conn:
            self._insert_entry(conn, "Google", "グーグル")

        captured_kwargs = {}

        def mock_synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
            captured_kwargs["kana_text"] = kana_text
            captured_kwargs["text"] = text
            with open(output_path, "w") as f:
                f.write("dummy")
            return True

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            mock_synthesize_line,
        )

        # 置換対象のテキストでスクリプトを作成
        ep_dir = tmp_path / "ep_replace"
        ep_dir.mkdir()
        self._create_script(ep_dir, [
            {"text": "Google announced", "section": "news", "speaker": "male"},
        ])

        from app.batch.synthesize_voicevox import synthesize_episode
        result = synthesize_episode(str(ep_dir))

        assert result == 1
        assert captured_kwargs.get("kana_text") == "グーグル announced", \
            f"置換ありの場合は置換後テキストが kana_text で渡されるべき, got {captured_kwargs.get('kana_text')!r}"
        assert captured_kwargs.get("text") == "グーグル announced", \
            "text パラメータも置換後テキストであること"

    def test_kana_text_not_passed_with_all_disabled_entries(self, test_env, tmp_path, monkeypatch):
        """全エントリ無効 = 置換なし → kana_text=None"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            self._insert_entry(conn, "Google", "グーグル", is_active=0)

        captured_kwargs = {}

        def mock_synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
            captured_kwargs["kana_text"] = kana_text
            with open(output_path, "w") as f:
                f.write("dummy")
            return True

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            mock_synthesize_line,
        )

        ep_dir = tmp_path / "ep_disabled"
        ep_dir.mkdir()
        self._create_script(ep_dir, [
            {"text": "Google announced", "section": "news", "speaker": "male"},
        ])

        from app.batch.synthesize_voicevox import synthesize_episode
        result = synthesize_episode(str(ep_dir))

        assert result == 1
        assert captured_kwargs.get("kana_text") is None, \
            "無効エントリのみの場合は置換なし → kana_text=None"

    def test_mixed_lines(self, test_env, tmp_path, monkeypatch):
        """置換対象・対象外が混在した場合、それぞれ正しく kana_text が渡されること"""
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            self._insert_entry(conn, "AWS", "エーダブリューエス")

        captured_calls = []

        def mock_synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
            captured_calls.append({"kana_text": kana_text, "text": text})
            with open(output_path, "w") as f:
                f.write("dummy")
            return True

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            mock_synthesize_line,
        )

        ep_dir = tmp_path / "ep_mixed"
        ep_dir.mkdir()
        self._create_script(ep_dir, [
            {"text": "AWS announced new services", "section": "news", "speaker": "male"},
            {"text": "次に通常のニュースです", "section": "news", "speaker": "female"},
            {"text": "AWS and Google", "section": "news", "speaker": "male"},
        ])

        from app.batch.synthesize_voicevox import synthesize_episode
        result = synthesize_episode(str(ep_dir))

        assert result == 3
        # 1行目: AWS → エーダブリューエス（置換あり → kana_text 設定）
        assert captured_calls[0]["kana_text"] == "エーダブリューエス announced new services"
        assert captured_calls[0]["text"] == "エーダブリューエス announced new services"
        # 2行目: 置換なし → kana_text=None
        assert captured_calls[1]["kana_text"] is None
        # 3行目: AWS が含まれる（置換あり → kana_text 設定）
        assert captured_calls[2]["kana_text"] == "エーダブリューエス and Google"
