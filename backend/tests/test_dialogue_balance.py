"""Tests for check_dialogue_balance (BEE-632): 山口(female)の質問偏重・
一問一答の連続を検知する自動検査ロジック。

対象: app/batch/review_script.py の check_dialogue_balance() と、
review_script() 本体への統合（review.json / 戻り値への反映）。
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_line(section: str, text: str = "", speaker: str = "male", article_id: int = 1) -> dict:
    return {"section": section, "text": text, "speaker": speaker, "article_id": article_id, "delivery": "neutral"}


class TestCheckDialogueBalanceQuestionOnly:
    """[YAMAGUCHI_QUESTION_ONLY]: newsブロック内で山口の発言が全て疑問文の場合を検出する。"""

    def test_all_female_lines_questions_detected(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "OpenAIが最新モデルを公開しました。", speaker="male"),
            _make_line("news", "また新しいモデルですか？", speaker="female"),
            _make_line("news", "それはどれくらい凄いんですか？", speaker="female"),
            _make_line("news", "かなり高性能なようです。", speaker="male"),
        ]
        issues = check_dialogue_balance(lines)
        question_only = [i for i in issues if "[YAMAGUCHI_QUESTION_ONLY]" in i]
        assert len(question_only) == 1

    def test_one_non_question_line_avoids_detection(self):
        """代表的な『掛け合い要件を満たす台本』(README実例) は合格すること。"""
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "OpenAIが最新モデルを公開しました。", speaker="male"),
            _make_line("news", "ある調査によると業務効率が最大40%向上したそうです。", speaker="male"),
            _make_line("news", "また新しいモデルですか。どれくらい凄いんですか？", speaker="female"),
            _make_line("news", "使い方によっては、日常の作業の進めやすさが変わるかもしれません。", speaker="male"),
            _make_line("news", "それなら仕事の効率化にもつながりそうで、期待しちゃいますね。", speaker="female"),
        ]
        issues = check_dialogue_balance(lines)
        assert issues == []

    def test_no_female_lines_in_block_no_issue(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "OpenAIが最新モデルを公開しました。", speaker="male"),
            _make_line("news", "業務効率が向上したとのことです。", speaker="male"),
        ]
        issues = check_dialogue_balance(lines)
        assert issues == []

    def test_half_width_question_mark_detected(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "発表がありました。", speaker="male"),
            _make_line("news", "本当ですか?", speaker="female"),
            _make_line("news", "本当です。", speaker="male"),
        ]
        issues = check_dialogue_balance(lines)
        assert any("[YAMAGUCHI_QUESTION_ONLY]" in i for i in issues)


class TestCheckDialogueBalanceQaRelay:
    """[QA_RELAY]: 山口の質問→田村の回答の1往復だけでnewsブロックが終わる場合を検出する。"""

    def test_single_qa_round_trip_detected(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "これって危険なんですか？", speaker="female"),
            _make_line("news", "はい、〜というリスクがあります。", speaker="male"),
        ]
        issues = check_dialogue_balance(lines)
        assert any("[QA_RELAY]" in i for i in issues)

    def test_followup_after_answer_avoids_relay_detection(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "これって危険なんですか？", speaker="female"),
            _make_line("news", "はい、〜というリスクがあります。", speaker="male"),
            _make_line("news", "なるほど、それなら気をつけたほうがよさそうですね。", speaker="female"),
        ]
        issues = check_dialogue_balance(lines)
        assert not any("[QA_RELAY]" in i for i in issues)

    def test_block_ending_on_female_non_question_no_relay(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "発表がありました。", speaker="male"),
            _make_line("news", "興味深いですね。", speaker="female"),
        ]
        issues = check_dialogue_balance(lines)
        assert issues == []

    def test_block_ending_on_male_question_no_relay(self):
        """質問者が田村(male)の場合は山口の質問偏重パターンではないので対象外。"""
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "この点についてどう思いますか？", speaker="male"),
            _make_line("news", "そうですね、気になります。", speaker="female"),
        ]
        issues = check_dialogue_balance(lines)
        assert not any("[QA_RELAY]" in i for i in issues)


class TestCheckDialogueBalanceSectionScope:
    """news以外のセクション（transition/discussion）は検査対象外であること。"""

    def test_transition_and_discussion_not_checked(self):
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            _make_line("transition", "続いてはAIの話題です。", speaker="female"),
            _make_line("discussion", "これはどうなんですか？", speaker="female"),
            _make_line("discussion", "そうですね。", speaker="male"),
            _make_line("outro", "以上です。", speaker="female"),
        ]
        issues = check_dialogue_balance(lines)
        assert issues == []

    def test_transition_separates_news_blocks(self):
        """記事間の news ブロックは独立に判定されること（片方が悪くても他方は影響を受けない）。"""
        from app.batch.review_script import check_dialogue_balance

        lines = [
            _make_line("news", "1つ目のニュースです。", speaker="male", article_id=1),
            _make_line("news", "本当ですか？", speaker="female", article_id=1),
            _make_line("news", "本当です。", speaker="male", article_id=1),
            _make_line("transition", "続いては次の話題です。", speaker="male", article_id=2),
            _make_line("news", "2つ目のニュースです。", speaker="male", article_id=2),
            _make_line("news", "面白いですね。", speaker="female", article_id=2),
        ]
        issues = check_dialogue_balance(lines)
        # article_id=1 のブロックのみで問題を検出し、article_id=2 のブロックは合格すること
        assert all("news行 [1]" in i or "news行 1〜2" in i for i in issues)
        assert any("[QA_RELAY]" in i for i in issues)
        assert any("[YAMAGUCHI_QUESTION_ONLY]" in i for i in issues)

    def test_empty_lines_no_error(self):
        from app.batch.review_script import check_dialogue_balance

        assert check_dialogue_balance([]) == []


class TestReviewScriptDialogueBalanceIntegration:
    """review_script() 本体に dialogue balance チェックが統合されていることを確認する。"""

    def _run(self, tmp_path, source_script, synth_lines, revision_summary="修正しました"):
        from app.batch.review_script import review_script

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        call_count = {"n": 0}

        def side_effect(prompt_text, **_kw):
            call_count["n"] += 1
            if call_count["n"] <= 5:
                return {"overall_score": 7, "issues": [], "general_feedback": ""}
            return {"lines": synth_lines, "revision_summary": revision_summary}

        mock_client = MagicMock()
        mock_client.generate_json.side_effect = side_effect
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            result = review_script(script_path, output_dir)

        return result, output_dir

    def test_revised_script_with_question_only_reports_issue(self, tmp_path):
        source_script = {
            "date": "2026-08-08",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            ],
        }
        synth_lines = [
            {"speaker": "male", "text": "OpenAIが新モデルを公開しました。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "それってすごいんですか？", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "male", "text": "はい、とても高性能です。", "article_id": 1, "section": "news", "delivery": "neutral"},
        ]

        result, output_dir = self._run(tmp_path, source_script, synth_lines)

        assert result["revised"] is True
        assert len(result["dialogue_balance_issues"]) >= 1
        assert any("[QA_RELAY]" in i or "[YAMAGUCHI_QUESTION_ONLY]" in i for i in result["dialogue_balance_issues"])

        review_json = json.loads(Path(output_dir, "review.json").read_text(encoding="utf-8"))
        assert review_json["dialogue_balance_issues"] == result["dialogue_balance_issues"]

    def test_revised_script_with_good_dialogue_no_issue(self, tmp_path):
        source_script = {
            "date": "2026-08-08",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            ],
        }
        synth_lines = [
            {"speaker": "male", "text": "OpenAIが新モデルを公開しました。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "それってすごいんですか？", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "male", "text": "はい、とても高性能です。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "それは楽しみですね。", "article_id": 1, "section": "news", "delivery": "neutral"},
        ]

        result, output_dir = self._run(tmp_path, source_script, synth_lines)

        assert result["revised"] is True
        assert result["dialogue_balance_issues"] == []

        review_json = json.loads(Path(output_dir, "review.json").read_text(encoding="utf-8"))
        assert review_json["dialogue_balance_issues"] == []

    def test_solo_style_skips_dialogue_balance_check(self, tmp_path):
        """solo（一人喋り）は対話が成立しないためチェック対象外であること。"""
        source_script = {
            "date": "2026-08-08",
            "title": "テスト解説",
            "subtitle": "",
            "style": "solo",
            "mc_gender": "female",
            "lines": [
                _make_line("intro", "解説を始めます。", speaker="female"),
            ],
        }
        # 疑問文だけが続く一人喋り（本来 dialogue なら検出対象になりうるパターン）
        synth_lines = [
            {"speaker": "female", "text": "これはどういうことなのでしょうか？", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "一体何が起きているのでしょうか？", "article_id": 1, "section": "news", "delivery": "neutral"},
        ]

        result, _output_dir = self._run(tmp_path, source_script, synth_lines)

        assert result["dialogue_balance_issues"] == []

    def test_synthesis_failure_falls_back_to_source_lines(self, tmp_path):
        """synthesis が失敗（revised=False）した場合は元の source.lines を検査すること。"""
        from app.batch.review_script import review_script

        source_script = {
            "date": "2026-08-08",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
                _make_line("news", "OpenAIが新モデルを公開しました。", speaker="male"),
                _make_line("news", "それってすごいんですか？", speaker="female"),
                _make_line("news", "はい、とても高性能です。", speaker="male"),
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        # generate_json は常に無効値（None）を返し synthesis を失敗させる
        mock_client = MagicMock()
        mock_client.generate_json.return_value = None
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            result = review_script(script_path, output_dir)

        assert result["revised"] is False
        assert any("[QA_RELAY]" in i for i in result["dialogue_balance_issues"])
