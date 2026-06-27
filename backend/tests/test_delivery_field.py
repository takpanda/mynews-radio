"""Tests for delivery field in script generation outputs.

Verifies that the 3 script generation modules emit "delivery": "neutral"
in every line dict they produce.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


def _mock_ollama_client(generate_json_return):
    """Return a patched OllamaClient context manager that returns `generate_json_return`
    from generate_json()."""
    client = MagicMock()
    client.generate_json.return_value = generate_json_return
    mock_cls = MagicMock()
    mock_cls.__enter__.return_value = client
    return mock_cls


class TestGenerateScriptDeliveryField:
    """generate_script() の出力する script.json に delivery フィールドが含まれること。"""

    def test_delivery_field_in_generate_script(self, tmp_path):
        from app.batch.generate_script import generate_script

        output = tmp_path / "script.json"
        fake_lines = [
            {"speaker": "male", "text": "こんにちは", "article_id": 1, "section": "intro"},
            {"speaker": "female", "text": "ニュースです", "article_id": 1, "section": "news"},
            {"speaker": "male", "text": "おわり", "article_id": 1, "section": "outro"},
        ]
        fake_response = {
            "title": "テスト番組",
            "subtitle": "サブタイトル",
            "lines": fake_lines,
        }

        with patch("app.batch.generate_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)), \
             patch("app.batch.generate_script.ArticleService.fetch_summaries_for_script",
                   return_value=[{"id": 1, "title": "テスト", "summary": "要約です。", "url": "https://example.com"}]), \
             patch("app.batch.generate_script.ArticleService.mark_articles_used"):

            count = generate_script(str(output))

        assert count > 0

        with open(output) as f:
            script = json.load(f)

        for i, line in enumerate(script["lines"]):
            assert "delivery" in line, f"line[{i}] に delivery キーがありません: {line}"
            assert line["delivery"] == "neutral", f"line[{i}] の delivery が 'neutral' ではありません: {line}"

    def test_delivery_field_in_ensure_transitions(self):
        """_ensure_transitions() が挿入する transition 行にも delivery が含まれること。"""
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "ニュース1", "summary": "要約1です。"},
            {"id": 2, "title": "ニュース2", "summary": "要約2です。"},
        ]
        lines = [
            {"section": "intro", "speaker": "male", "text": "番組開始"},
            {"section": "news", "article_id": 1, "speaker": "female", "text": "ニュース1の内容"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "ニュース2の内容"},
        ]

        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) > 0, "transition 行が挿入されていません"
        for i, line in enumerate(transitions):
            assert "delivery" in line, f"transition line[{i}] に delivery キーがありません: {line}"
            assert line["delivery"] == "neutral", f"transition line[{i}] の delivery が 'neutral' ではありません: {line}"

    def test_existing_keys_not_affected(self, tmp_path):
        """delivery 追加により既存キー(speaker, text, article_id, section)が影響を受けていないこと。"""
        from app.batch.generate_script import generate_script

        output = tmp_path / "script.json"
        fake_lines = [
            {"speaker": "male", "text": "こんにちは", "article_id": 42, "section": "intro"},
        ]
        fake_response = {"title": "テスト", "subtitle": "", "lines": fake_lines}

        with patch("app.batch.generate_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)), \
             patch("app.batch.generate_script.ArticleService.fetch_summaries_for_script",
                   return_value=[{"id": 42, "title": "テスト", "summary": "要約です。", "url": "https://example.com"}]), \
             patch("app.batch.generate_script.ArticleService.mark_articles_used"):

            generate_script(str(output))

        with open(output) as f:
            script = json.load(f)

        line = script["lines"][0]
        assert line["speaker"] == "male"
        assert line["text"] == "こんにちは"
        assert line["article_id"] == 42
        assert line["section"] == "intro"

    def test_llm_delivery_value_is_preserved(self, tmp_path):
        """LLM が出力した delivery 値（thoughtful）がそのまま保持されること。"""
        from app.batch.generate_script import generate_script

        output = tmp_path / "script.json"
        fake_lines = [
            {"speaker": "male", "text": "配信開始", "article_id": 1, "section": "intro", "delivery": "warm"},
            {"speaker": "female", "text": "ニュースです", "article_id": 1, "section": "news", "delivery": "thoughtful"},
            {"speaker": "male", "text": "次の話題です", "article_id": 2, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "おわり", "article_id": 2, "section": "outro", "delivery": "neutral"},
        ]
        fake_response = {
            "title": "テスト番組",
            "subtitle": "",
            "lines": fake_lines,
        }

        with patch("app.batch.generate_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)), \
             patch("app.batch.generate_script.ArticleService.fetch_summaries_for_script",
                   return_value=[{"id": 1, "title": "テスト1", "summary": "要約1です。", "url": "https://example.com"},
                                 {"id": 2, "title": "テスト2", "summary": "要約2です。", "url": "https://example.com"}]), \
             patch("app.batch.generate_script.ArticleService.mark_articles_used"):

            count = generate_script(str(output))

        assert count > 0

        with open(output) as f:
            script = json.load(f)

        expected = {"warm", "thoughtful", "questioning", "neutral"}
        actual = {l.get("delivery") for l in script["lines"] if l.get("section") != "transition"}
        assert actual & expected, f"LLM 出力の delivery 値が保持されていません: actual={actual}"
        assert "thoughtful" in {l["delivery"] for l in script["lines"] if l.get("section") == "news"}, \
            "thoughtful が news 行に保持されていません"

    def test_ensure_transitions_delivery_always_neutral(self):
        """_ensure_transitions() が挿入する transition 行の delivery は常に neutral。"""
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "ニュース1", "summary": "要約1です。"},
            {"id": 2, "title": "ニュース2", "summary": "要約2です。"},
        ]
        lines = [
            {"section": "intro", "speaker": "male", "text": "番組開始"},
            {"section": "news", "article_id": 1, "speaker": "female", "text": "ニュース1の内容", "delivery": "thoughtful"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "ニュース2の内容", "delivery": "questioning"},
        ]

        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) > 0
        for i, line in enumerate(transitions):
            assert line["delivery"] == "neutral", \
                f"transition line[{i}] の delivery は常に neutral であるべき: {line}"


class TestCommentaryScriptDeliveryField:
    """generate_commentary_script() の出力する script.json に delivery フィールドが含まれること。"""

    def test_delivery_field_in_commentary_script(self, tmp_path):
        from app.batch.generate_commentary_script import generate_commentary_script

        output = tmp_path / "commentary_script.json"
        article = {"id": 1, "title": "テスト記事", "text": "本文です。"}

        fake_lines = [
            {"speaker": "male", "text": "解説を始めます", "article_id": 1, "section": "intro"},
            {"speaker": "male", "text": "これが内容です", "article_id": 1, "section": "news"},
            {"speaker": "male", "text": "以上です", "article_id": 1, "section": "outro"},
        ]
        fake_response = {"title": "テスト記事", "subtitle": "", "lines": fake_lines}

        with patch("app.batch.generate_commentary_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)):

            count = generate_commentary_script(str(output), article, style="solo")

        assert count > 0

        with open(output) as f:
            script = json.load(f)

        for i, line in enumerate(script["lines"]):
            assert "delivery" in line, f"line[{i}] に delivery キーがありません: {line}"
            assert line["delivery"] == "neutral", f"line[{i}] の delivery が 'neutral' ではありません: {line}"

    def test_commentary_existing_keys_not_affected(self, tmp_path):
        """delivery 追加により既存キーが影響を受けていないこと（commentary）。"""
        from app.batch.generate_commentary_script import generate_commentary_script

        output = tmp_path / "commentary_script.json"
        article = {"id": 99, "title": "テスト記事", "text": "本文です。"}

        fake_lines = [
            {"speaker": "male", "text": "解説です", "article_id": 99, "section": "intro"},
        ]
        fake_response = {"title": "テスト記事", "subtitle": "", "lines": fake_lines}

        with patch("app.batch.generate_commentary_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)):

            generate_commentary_script(str(output), article, style="solo")

        with open(output) as f:
            script = json.load(f)

        line = script["lines"][0]
        assert line["speaker"] == "male"
        assert line["text"] == "解説です"
        assert line["article_id"] == 99
        assert line["section"] == "intro"

    def test_commentary_llm_delivery_value_is_preserved(self, tmp_path):
        """LLM が出力した delivery 値（commentary）がそのまま保持されること。"""
        from app.batch.generate_commentary_script import generate_commentary_script

        output = tmp_path / "commentary_script.json"
        article = {"id": 1, "title": "テスト記事", "text": "本文です。"}

        fake_lines = [
            {"speaker": "male", "text": "解説を始めます", "article_id": 1, "section": "intro", "delivery": "warm"},
            {"speaker": "male", "text": "これが内容です", "article_id": 1, "section": "news", "delivery": "thoughtful"},
            {"speaker": "male", "text": "以上です", "article_id": 1, "section": "outro", "delivery": "questioning"},
        ]
        fake_response = {"title": "テスト記事", "subtitle": "", "lines": fake_lines}

        with patch("app.batch.generate_commentary_script.OllamaClient",
                   return_value=_mock_ollama_client(fake_response)):

            count = generate_commentary_script(str(output), article, style="solo")

        assert count > 0

        with open(output) as f:
            script = json.load(f)

        expected = {"warm", "thoughtful", "questioning"}
        actual = {l.get("delivery") for l in script["lines"]}
        assert actual & expected, f"LLM 出力の delivery 値が保持されていません: actual={actual}"


class TestReviewScriptDeliveryField:
    """_build_revised_script() が返す line dict に delivery フィールドが含まれること。"""

    def test_delivery_field_in_revised_script(self):
        from app.batch.review_script import _build_revised_script

        source = {
            "date": "2026-06-23",
            "title": "元のタイトル",
            "subtitle": "元のサブタイトル",
            "lines": [],
        }
        response = {
            "title": "改訂タイトル",
            "subtitle": "改訂サブタイトル",
            "lines": [
                {"speaker": "male", "text": "改訂版", "article_id": 1, "section": "news"},
                {"speaker": "female", "text": "訂正しました", "article_id": 1, "section": "outro"},
            ],
        }

        revised = _build_revised_script(source, response)

        for i, line in enumerate(revised["lines"]):
            assert "delivery" in line, f"line[{i}] に delivery キーがありません: {line}"
            assert line["delivery"] == "neutral", f"line[{i}] の delivery が 'neutral' ではありません: {line}"

    def test_review_existing_keys_not_affected(self):
        from app.batch.review_script import _build_revised_script

        source = {"date": "2026-06-23", "title": "", "subtitle": "", "lines": []}
        response = {
            "title": "", "subtitle": "",
            "lines": [
                {"speaker": "female", "text": "改訂テキスト", "article_id": 5, "section": "intro"},
            ],
        }

        revised = _build_revised_script(source, response)
        line = revised["lines"][0]

        assert line["speaker"] == "female"
        assert line["text"] == "改訂テキスト"
        assert line["article_id"] == 5
        assert line["section"] == "intro"

    def test_review_llm_delivery_value_is_preserved(self):
        """_build_revised_script() で LLM の non-neutral delivery が保持されること。"""
        from app.batch.review_script import _build_revised_script

        source = {
            "date": "2026-06-23",
            "title": "元のタイトル",
            "subtitle": "元のサブタイトル",
            "lines": [],
        }
        response = {
            "title": "改訂タイトル",
            "subtitle": "改訂サブタイトル",
            "lines": [
                {"speaker": "male", "text": "改訂版", "article_id": 1, "section": "news", "delivery": "thoughtful"},
                {"speaker": "female", "text": "訂正しました", "article_id": 1, "section": "outro", "delivery": "warm"},
            ],
        }

        revised = _build_revised_script(source, response)

        for line in revised["lines"]:
            if line["section"] == "news":
                assert line["delivery"] == "thoughtful", f"news の delivery が thoughtful ではありません: {line}"
            elif line["section"] == "outro":
                assert line["delivery"] == "warm", f"outro の delivery が warm ではありません: {line}"
