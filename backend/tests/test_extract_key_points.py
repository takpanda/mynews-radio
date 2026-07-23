"""Tests for _extract_key_points in radio_pipeline.py."""

import json
import os

from app.batch.radio_pipeline import _extract_key_points


class TestExtractKeyPoints:
    """_extract_key_points の抽出ロジック単体テスト"""

    def _make_script(self, lines: list[dict] | None = None, subtitle: str = "") -> dict:
        return {
            "title": "ニュースのとなり",
            "subtitle": subtitle,
            "lines": lines or [],
        }

    def test_extract_from_intro_lines(self, tmp_path):
        """intro行のラインアップ記述から要点が抽出される"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "今日のラインアップは、AI・セキュリティ・経済の3本です。", "section": "intro"},
                {"speaker": "female", "text": "盛りだくさんですね。", "section": "intro"},
            ],
            subtitle="AI・セキュリティ・経済",
        )
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text("[]", encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert len(points) >= 1
        assert "ラインアップ" in points[0]

    def test_fallback_to_subtitle(self, tmp_path):
        """intro行に該当がない場合、subtitleから抽出される"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "こんにちは。", "section": "intro"},
            ],
            subtitle="AIの最新動向と社会への影響",
        )
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text("[]", encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert len(points) >= 1
        assert points[0] == "AIの最新動向と社会への影響"

    def test_fallback_to_article_titles(self, tmp_path):
        """intro/subtitle不足時、記事タイトルで補完される"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "こんにちは。", "section": "intro"},
                {"speaker": "male", "text": "記事Aの内容です。", "section": "news", "article_id": 1},
                {"speaker": "male", "text": "記事Bの内容です。", "section": "news", "article_id": 2},
            ],
            subtitle="",
        )
        summaries = [
            {"article_id": 1, "title": "OpenAI新モデル発表", "summary": "..."},
            {"article_id": 2, "title": "セキュリティ最新情報", "summary": "..."},
        ]
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert "OpenAI新モデル発表" in points
        assert "セキュリティ最新情報" in points

    def test_max_3_points(self, tmp_path):
        """最大3件までで,4件目は含まれない"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "今日のニュースはAとBとCとDです。", "section": "intro"},
                {"speaker": "male", "text": "今日のトピックも盛りだくさん。", "section": "intro"},
                {"speaker": "male", "text": "本日もよろしくお願いします。", "section": "intro"},
                {"speaker": "male", "text": "ニュースをお届けします。", "section": "intro"},
            ],
            subtitle="",
        )
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text("[]", encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert len(points) <= 3

    def test_empty_script_returns_empty(self, tmp_path):
        """空のスクリプトでは空リストが返る"""
        script = self._make_script(lines=[], subtitle="")
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text("[]", encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert points == []

    def test_no_intro_lines_returns_empty(self, tmp_path):
        """該当するintro行がない場合も空リストが返る"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "A", "section": "news"},
            ],
            subtitle="",
        )
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text("[]", encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        assert points == []

    def test_summaries_file_not_found(self, tmp_path):
        """summaries.jsonが存在しなくてもエラーにならない"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "今日のラインアップをお届けします。", "section": "intro"},
            ],
            subtitle="テスト番組",
        )
        points = _extract_key_points(script, str(tmp_path / "nonexistent.json"))
        assert len(points) >= 1

    def test_article_title_fallback_order(self, tmp_path):
        """記事タイトルはscript内のarticle_id登場順に追加される"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "こんにちは。", "section": "intro"},
                {"speaker": "male", "text": "記事B", "section": "news", "article_id": 2},
                {"speaker": "male", "text": "記事A", "section": "news", "article_id": 1},
            ],
            subtitle="",
        )
        summaries = [
            {"article_id": 1, "title": "タイトルA", "summary": ""},
            {"article_id": 2, "title": "タイトルB", "summary": ""},
        ]
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        # introに該当がないのでsubtitle→空→記事タイトルへ
        assert "タイトルB" in points
        assert "タイトルA" in points

    def test_combined_sources(self, tmp_path):
        """intro, subtitle, article_title の複合ソースを最大3件まで結合する"""
        script = self._make_script(
            lines=[
                {"speaker": "male", "text": "今日のラインアップは3本です。", "section": "intro"},
                {"speaker": "male", "text": "記事X", "section": "news", "article_id": 10},
                {"speaker": "male", "text": "記事Y", "section": "news", "article_id": 20},
            ],
            subtitle="サブタイトル",
        )
        summaries = [
            {"article_id": 10, "title": "タイトルX", "summary": ""},
            {"article_id": 20, "title": "タイトルY", "summary": ""},
        ]
        summaries_file = tmp_path / "summaries.json"
        summaries_file.write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")

        points = _extract_key_points(script, str(summaries_file))
        # intro → subtitle の順で埋まり、残りがタイトルで補完
        assert len(points) <= 3
        assert points[0] == "今日のラインアップは3本です。"
        assert points[1] == "サブタイトル"
