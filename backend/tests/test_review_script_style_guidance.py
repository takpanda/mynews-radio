"""Tests for radio director style-guard branching in review_script.

Verifies that _build_radio_director_style_guidance() returns the correct
evaluation axes for solo / dialogue / radio scripts, and that the full
review_script() flow passes the right guidance into the LLM prompt.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


def _mock_ollama_client(generate_json_return):
    """Return a patched OllamaClient context manager."""
    client = MagicMock()
    client.generate_json.return_value = generate_json_return
    mock_cls = MagicMock()
    mock_cls.__enter__.return_value = client
    return mock_cls


class TestBuildRadioDirectorStyleGuidance:
    """_build_radio_director_style_guidance() の戻り値を検証するテスト。"""

    EXPECTED_SOLO_MARKERS = [
        "一人喋り",
        "solo",
        "対話・掛け合いは存在しません",
        "一人の語り手としてのテンポ",
        "ナレーションとしての自然な流れ",
        "評価対象外",
        "MC間の対話バランス",
        "男女交互発話",
        "Contextual Bridge",
    ]

    EXPECTED_DIALOGUE_MARKERS = [
        "二人対談",
        "dialogue",
        "交互に発話",
        "対話バランス",
        "男女交互に喋っているか",
        "Contextual Bridge",
        "前の話題に自然に言及",
    ]

    def test_solo_returns_solo_guidance(self):
        """style="solo" に対して solo 用評価軸が返ること。"""
        from app.batch.review_script import _build_radio_director_style_guidance

        result = _build_radio_director_style_guidance("solo")

        assert "一人喋り" in result
        assert "MC間の対話バランス" in result  # 「評価対象外」で言及
        assert "一人の語り手としてのテンポ" in result

    def test_dialogue_returns_dialogue_guidance(self):
        """style="dialogue" に対して dialogue 用評価軸が返ること。"""
        from app.batch.review_script import _build_radio_director_style_guidance

        result = _build_radio_director_style_guidance("dialogue")

        assert "二人対談" in result
        assert "対話バランス" in result
        assert "男女交互に喋っているか" in result
        assert "Contextual Bridge" in result
        assert "前の話題に自然に言及" in result

    def test_empty_style_defaults_to_dialogue(self):
        """style="" (radio script) に対して dialogue 用評価軸が返ること。"""
        from app.batch.review_script import _build_radio_director_style_guidance

        result = _build_radio_director_style_guidance("")

        assert "二人対談" in result
        assert "対話バランス" in result

    def test_solo_does_not_skip_listerning_pacing(self):
        """solo ガイダンスには聴きやすさ・テンポの評価観点が含まれること。"""
        from app.batch.review_script import _build_radio_director_style_guidance

        result = _build_radio_director_style_guidance("solo")

        for marker in self.EXPECTED_SOLO_MARKERS:
            assert marker in result, f"soloガイダンスに期待文字列がありません: {marker}"

    def test_dialogue_guidance_contains_transition_examples(self):
        """dialogue ガイダンスに transition の具体例が含まれること。"""
        from app.batch.review_script import _build_radio_director_style_guidance

        result = _build_radio_director_style_guidance("dialogue")

        assert "続いては気象に関する話題です" in result
        assert "そういった極限的な脅威から視点を移して" in result


class TestReviewScriptRadioDirectorPrompt:
    """review_script() 内で radio director に渡されるプロンプトを検証するテスト。"""

    def _assert_prompt_contains(self, tmp_path, source_script, expected_markers):
        """Mock 環境で review_script を実行し、LLM へのプロンプト文字列に
        expected_markers が全て含まれることを確認する。"""
        from app.batch.review_script import review_script

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Mock: only radio director is called, others return empty
        def side_effect(prompt_text, **_kw):
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        def _mock_ollama_client(prompt_text):
            return mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            result = review_script(script_path, output_dir)

        assert result["review_count"] == len(("genius", "beginner", "worried", "positive", "radio"))
        assert "radio" in result.get("revision_summary", "") or result["review_count"] > 0

    def test_solo_prompt_contains_solo_guidance(self, tmp_path):
        """solo スクリプトで radio director に一人喋り用ガイダンスが渡ること。"""
        source_script = {
            "date": "2026-07-09",
            "title": "テスト解説",
            "subtitle": "",
            "style": "solo",
            "mc_gender": "male",
            "lines": [
                {"speaker": "male", "text": "解説開始", "article_id": 1, "section": "intro", "delivery": "neutral"},
                {"speaker": "male", "text": "内容を説明します", "article_id": 1, "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "以上です", "article_id": 1, "section": "outro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        # Find the radio director prompt (5th director, so 5th call)
        radio_prompt = captured_prompts[4]  # 5 directors, radio is last
        assert "一人喋り" in radio_prompt, "solo ガイダンスがプロンプトに含まれていません"
        assert "評価対象外" in radio_prompt, "solo の評価対象外リストがプロンプトに含まれていません"
        assert "MC間の対話バランス" in radio_prompt, "対話バランスが評価対象外で言及されていません"

    def test_dialogue_prompt_contains_dialogue_guidance(self, tmp_path):
        """dialogue スクリプトで radio director に二人対談用ガイダンスが渡ること。"""
        source_script = {
            "date": "2026-07-09",
            "title": "テスト番組",
            "subtitle": "",
            "style": "dialogue",
            "mc_gender": "male",
            "lines": [
                {"speaker": "male", "text": "開始します", "article_id": 1, "section": "intro", "delivery": "neutral"},
                {"speaker": "female", "text": "内容です", "article_id": 1, "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "終わります", "article_id": 1, "section": "outro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        radio_prompt = captured_prompts[4]
        assert "二人対談" in radio_prompt, "dialogue ガイダンスがプロンプトに含まれていません"
        assert "対話バランス" in radio_prompt
        assert "Contextual Bridge" in radio_prompt
        assert "男女交互に喋っているか" in radio_prompt

    def test_radio_script_defaults_to_dialogue_guidance(self, tmp_path):
        """radio 台本（style なし）で dialogue 用ガイダンスが渡ること。"""
        source_script = {
            "date": "2026-07-09",
            "title": "ラジオ番組",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "番組開始", "article_id": 1, "section": "intro", "delivery": "neutral"},
                {"speaker": "female", "text": "ニュースです", "article_id": 1, "section": "news", "delivery": "neutral"},
                {"speaker": "male", "text": "おわり", "article_id": 1, "section": "outro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        radio_prompt = captured_prompts[4]
        assert "二人対談" in radio_prompt, "radio 台本も dialogue ガイダンスが渡されること"
        assert "対話バランス" in radio_prompt
        # solo ガイダンスが含まれないことを確認
        assert "一人喋り" not in radio_prompt, "radio 台本に solo ガイダンスが含まれていてはならない"


class TestBuildOutputIssueExample:
    """_build_output_issue_example() の戻り値を検証するテスト。"""

    def test_solo_contains_solo_issue(self):
        """style="solo" に一人喋り用の issue 例が含まれること。"""
        from app.batch.review_script import _build_output_issue_example

        result = _build_output_issue_example("solo")

        assert "一人喋りが単調" in result
        assert "メリハリに欠ける" in result
        assert "transition" not in result, "solo モードに transition の例が含まれていてはならない"

    def test_dialogue_contains_transition_issue(self):
        """style="dialogue" に transition 用の issue 例が含まれること。"""
        from app.batch.review_script import _build_output_issue_example

        result = _build_output_issue_example("dialogue")

        assert "transition" in result
        assert "前の話題への言及" in result
        assert "一人喋り" not in result, "dialogue に solo 例が含まれていてはならない"

    def test_empty_style_defaults_to_dialogue_issue(self):
        """style="" (radio) は dialogue 用の issue 例が返ること。"""
        from app.batch.review_script import _build_output_issue_example

        result = _build_output_issue_example("")

        assert "transition" in result
        assert "一人喋り" not in result


class TestReviewScriptOutputIssueExample:
    """プロンプト全体の出力例部分を検証するテスト。"""

    def test_solo_prompt_does_not_contain_transition_example(self, tmp_path):
        """solo スクリプトの radio director プロンプトに transition issue 例が含まれないこと。"""
        source_script = {
            "date": "2026-07-09",
            "title": "テスト解説",
            "subtitle": "",
            "style": "solo",
            "mc_gender": "male",
            "lines": [
                {"speaker": "male", "text": "解説開始", "article_id": 1, "section": "intro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        radio_prompt = captured_prompts[4]
        # solo モードでは transition の具体例が出力例として含まれていないことを厳格に確認
        assert "transitionで前の話題への言及がなく" not in radio_prompt, \
            "solo モードで transition の issue 例が出力例に残っていてはならない"
        assert "一人喋りが単調" in radio_prompt, \
            "solo モードでは一人喋り用の issue 例が出力例に含まれること"

    def test_dialogue_prompt_contains_transition_example(self, tmp_path):
        """dialogue スクリプトの radio director プロンプトに transition issue 例が含まれること。"""
        source_script = {
            "date": "2026-07-09",
            "title": "テスト番組",
            "subtitle": "",
            "style": "dialogue",
            "mc_gender": "male",
            "lines": [
                {"speaker": "male", "text": "開始", "article_id": 1, "section": "intro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        radio_prompt = captured_prompts[4]
        assert "transitionで前の話題への言及がなく" in radio_prompt, \
            "dialogue モードでは transition の issue 例が出力例に含まれること"
        assert "一人喋りが単調" not in radio_prompt, \
            "dialogue モードに solo 用の issue 例が含まれていてはならない"

    def test_radio_prompt_contains_transition_example(self, tmp_path):
        """radio 台本（style なし）の radio director プロンプトに transition issue 例が含まれること。"""
        source_script = {
            "date": "2026-07-09",
            "title": "ラジオ番組",
            "subtitle": "",
            "lines": [
                {"speaker": "male", "text": "番組開始", "article_id": 1, "section": "intro", "delivery": "neutral"},
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        captured_prompts = []

        def side_effect(prompt_text, **_kw):
            captured_prompts.append(prompt_text)
            return {"overall_score": 7, "issues": [], "general_feedback": ""}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            from app.batch.review_script import review_script
            review_script(script_path, output_dir)

        radio_prompt = captured_prompts[4]
        assert "transitionで前の話題への言及がなく" in radio_prompt, \
            "radio 台本でも transition の issue 例が出力例に含まれること"

    def test_prompt_has_no_unescaped_template_braces(self, tmp_path):
        """radio director プロンプト全体に {{ が残っていないこと。"""
        from app.batch.review_script import _load_prompt, _build_radio_director_style_guidance, _build_output_issue_example

        template = _load_prompt("review_radio_director.md")
        # Verify the template itself has no {{ (output_example replaced it)
        assert "{{" not in template, \
            "review_radio_director.md に {{ が残っています"

        # Verify for all three styles
        for style in ("solo", "dialogue", ""):
            style_guidance = _build_radio_director_style_guidance(style)
            output_issue_example = _build_output_issue_example(style)
            prompt = template.format(
                script_json='{"lines": []}',
                style_guidance=style_guidance,
                output_issue_example=output_issue_example,
            )
            assert "{{" not in prompt, \
                f"style='{style}' のプロンプトに {{ が残っています"
            assert "}}" not in prompt, \
                f"style='{style}' のプロンプトに }} が残っています"
