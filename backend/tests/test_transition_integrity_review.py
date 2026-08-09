"""Tests for check_transition_integrity (BEE-661/BEE-662): レビュー工程で、
記事境界のtransitionに前の記事の締め文と次の記事の告知が混在した壊れた文が
残っていないかを検知する自動検査ロジック。

対象: app/batch/review_script.py の check_transition_integrity() と、
review_script() 本体への統合（review.json / 戻り値への反映）。

生成工程（app/batch/generate_script.py の _ensure_transitions()）は同じ判定
条件（_is_broken_transition_text）で壊れたtransitionを検知し安全なテンプレート
へ置換するため、レビュー工程はその置換が正しく行われた前提の script.json を
入力とする。本テストのレビュー工程側チェックは、レビューLLMによる再統合
（review_synthesize.md）で新たに複文混在のtransitionが生成し直された場合の
検知のみを対象とし、自動修正は行わない（review工程は次の記事の正しい
トピックを持たないため安全な置換文を再構成できない）。
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_line(section: str, text: str = "", speaker: str = "male", article_id: int = 1) -> dict:
    return {"section": section, "text": text, "speaker": speaker, "article_id": article_id, "delivery": "neutral"}


_BROKEN_TEXT = (
    "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
    "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
    "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。"
)


class TestCheckTransitionIntegrity:
    """check_transition_integrity() の判定条件そのものを検証する。"""

    def test_bee661_broken_transition_before_news_detected(self):
        from app.batch.review_script import check_transition_integrity

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            _make_line("news", "海外邦人についての記事です。", speaker="male", article_id=1),
            _make_line("transition", _BROKEN_TEXT, speaker="female", article_id=2),
            _make_line("news", "行方不明事案についての記事です。", speaker="male", article_id=2),
        ]
        issues = check_transition_integrity(lines)
        assert any("[TRANSITION_MIXED]" in i for i in issues)

    def test_normal_transition_before_news_not_flagged(self):
        from app.batch.review_script import check_transition_integrity

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            _make_line("news", "記事1の内容です。", speaker="male", article_id=1),
            _make_line("transition", "それでは、経済ニュースの話題に移ります。", speaker="female", article_id=2),
            _make_line("news", "記事2の内容です。", speaker="male", article_id=2),
        ]
        issues = check_transition_integrity(lines)
        assert issues == []

    def test_discussion_precursor_two_sentence_style_not_flagged(self):
        """discussion直前のtransitionは複文スタイルが正常なため対象外であること。"""
        from app.batch.review_script import check_transition_integrity

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            _make_line("news", "記事1の内容です。", speaker="male", article_id=1),
            _make_line("transition", "気になりますね。どう思います？", speaker="female", article_id=1),
            _make_line("discussion", "深掘りします。", speaker="male", article_id=1),
        ]
        issues = check_transition_integrity(lines)
        assert issues == []

    def test_broken_text_not_immediately_before_news_not_flagged(self):
        """次の行がnewsでないtransitionブロック（記事境界以外）は対象外であること。"""
        from app.batch.review_script import check_transition_integrity

        lines = [
            _make_line("news", "記事1の内容です。", speaker="male", article_id=1),
            _make_line("transition", _BROKEN_TEXT, speaker="female", article_id=1),
            _make_line("outro", "以上です。", speaker="male"),
        ]
        issues = check_transition_integrity(lines)
        assert issues == []

    def test_empty_lines_no_error(self):
        from app.batch.review_script import check_transition_integrity

        assert check_transition_integrity([]) == []


class TestReviewScriptTransitionIntegrityIntegration:
    """review_script() 本体に transition integrity チェックが統合されていることを確認する。"""

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

    def test_revised_script_with_broken_transition_reports_issue(self, tmp_path):
        source_script = {
            "date": "2026-08-09",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            ],
        }
        synth_lines = [
            {"speaker": "male", "text": "海外邦人についての記事です。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": _BROKEN_TEXT, "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "行方不明事案についての記事です。", "article_id": 2, "section": "news", "delivery": "neutral"},
        ]

        result, output_dir = self._run(tmp_path, source_script, synth_lines)

        assert result["revised"] is True
        assert any("[TRANSITION_MIXED]" in i for i in result["transition_integrity_issues"])

        review_json = json.loads(Path(output_dir, "review.json").read_text(encoding="utf-8"))
        assert review_json["transition_integrity_issues"] == result["transition_integrity_issues"]
        # 非fatalであるため、問題があっても revised=True のまま script.json は出力される
        assert Path(output_dir, "script.json").exists()

    def test_revised_script_with_clean_transitions_no_issue(self, tmp_path):
        source_script = {
            "date": "2026-08-09",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
            ],
        }
        synth_lines = [
            {"speaker": "male", "text": "記事1の内容です。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "それでは、記事2の話題に移ります。", "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "記事2の内容です。", "article_id": 2, "section": "news", "delivery": "neutral"},
        ]

        result, output_dir = self._run(tmp_path, source_script, synth_lines)

        assert result["revised"] is True
        assert result["transition_integrity_issues"] == []

        review_json = json.loads(Path(output_dir, "review.json").read_text(encoding="utf-8"))
        assert review_json["transition_integrity_issues"] == []

    def test_synthesis_failure_falls_back_to_source_lines(self, tmp_path):
        """synthesis が失敗（revised=False）した場合は元の source.lines を検査すること。"""
        from app.batch.review_script import review_script

        source_script = {
            "date": "2026-08-09",
            "title": "ニュースのとなり",
            "subtitle": "",
            "lines": [
                _make_line("intro", "「ニュースのとなり」の時間です。", speaker="male"),
                _make_line("news", "記事1の内容です。", speaker="male", article_id=1),
                _make_line("transition", _BROKEN_TEXT, speaker="female", article_id=2),
                _make_line("news", "記事2の内容です。", speaker="male", article_id=2),
            ],
        }

        script_path = os.path.join(tmp_path, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(source_script, f, ensure_ascii=False)

        output_dir = os.path.join(tmp_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        mock_client = MagicMock()
        mock_client.generate_json.return_value = None
        mock_cls = MagicMock()
        mock_cls.__enter__.return_value = mock_client

        with patch("app.batch.review_script.OllamaClient", return_value=mock_cls):
            result = review_script(script_path, output_dir)

        assert result["revised"] is False
        assert any("[TRANSITION_MIXED]" in i for i in result["transition_integrity_issues"])
