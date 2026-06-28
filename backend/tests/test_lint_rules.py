"""Tests for lint_script: 5 new lint rules + regression tests for existing rules."""
import pytest


def _make_line(section: str, text: str = "", speaker: str = "male", article_id: int = 1) -> dict:
    return {"section": section, "text": text, "speaker": speaker, "article_id": article_id}


class TestIntroFormatCheck:
    """ルール1: introフォーマットチェック [INTRO_FORMAT] (ERROR)"""

    def test_intro_first_line_correct_format_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。今日も様々なニュースをお届けします。"),
            _make_line("intro", "まずは国内の話題から。"),
        ]
        errors = lint_script(lines)
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 0

    def test_intro_first_line_wrong_format_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "こんにちは、ニュースの時間です。"),
            _make_line("intro", "まずは国内の話題から。"),
        ]
        errors = lint_script(lines)
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 1
        assert "「ニュースのとなり」の時間です" in intro_errors[0]

    def test_intro_missing_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("news", "今日のニュースをお伝えします。"),
        ]
        errors = lint_script(lines)
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 1
        assert "introセクションが存在しません" in intro_errors[0]

    def test_intro_first_line_correct_custom_program_name(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「別番組」の時間です。今日も様々なニュースをお届けします。"),
        ]
        errors = lint_script(lines, program_name="別番組")
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 0

    def test_intro_first_line_wrong_format_custom_program_name(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「間違った番組名」の時間です。"),
        ]
        errors = lint_script(lines, program_name="別番組")
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 1
        assert "「別番組」の時間です" in intro_errors[0]

    def test_intro_first_line_empty_text_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", ""),
        ]
        errors = lint_script(lines)
        intro_errors = [e for e in errors if "[INTRO_FORMAT]" in e]
        assert len(intro_errors) == 1


class TestIntroLineupCheck:
    """ルール2: introラインアップチェック [INTRO_LINEUP] (WARN)"""

    def test_intro_with_sufficient_lineup_keywords_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("intro", "今日のラインナップはこちらです。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 0

    def test_intro_without_lineup_keywords_raises_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("intro", "それでは最初の話題です。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 1
        assert "ラインアップを示唆する表現が不足" in lineup_errors[0]

    def test_intro_only_one_keyword_raises_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("intro", "それでは最初の話題です。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 1

    def test_intro_exactly_two_keywords_no_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("intro", "本日は3つのトピックをご用意しました。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 0

    def test_intro_with_four_keywords_no_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("intro", "今日の本日のラインナップとニューストピックをお届けします。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 0

    def test_no_intro_section_no_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("news", "今日のニュースをお伝えします。"),
        ]
        errors = lint_script(lines)
        lineup_errors = [e for e in errors if "[INTRO_LINEUP]" in e]
        assert len(lineup_errors) == 0


class TestOutroRichnessCheck:
    """ルール3: outro充実度チェック [OUTRO_LENGTH] (ERROR)"""

    def test_outro_two_lines_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("outro", "以上、今日のニュースをお届けしました。"),
            _make_line("outro", "また明日お会いしましょう。"),
        ]
        errors = lint_script(lines)
        outro_errors = [e for e in errors if "[OUTRO_LENGTH]" in e]
        assert len(outro_errors) == 0

    def test_outro_more_than_two_lines_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("outro", "以上、今日のニュースをお届けしました。"),
            _make_line("outro", "詳しくは番組ホームページをご覧ください。"),
            _make_line("outro", "また明日お会いしましょう。"),
        ]
        errors = lint_script(lines)
        outro_errors = [e for e in errors if "[OUTRO_LENGTH]" in e]
        assert len(outro_errors) == 0

    def test_outro_one_line_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("outro", "以上、今日のニュースをお届けしました。"),
        ]
        errors = lint_script(lines)
        outro_errors = [e for e in errors if "[OUTRO_LENGTH]" in e]
        assert len(outro_errors) == 1
        assert "最低2行必要" in outro_errors[0]

    def test_outro_zero_lines_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
        ]
        errors = lint_script(lines)
        outro_errors = [e for e in errors if "[OUTRO_LENGTH]" in e]
        assert len(outro_errors) == 1
        assert "0行" in outro_errors[0]


class TestTransitionVariationCheck:
    """ルール4: transitionバリエーションチェック [TRANS_VARIATION] (ERROR)"""

    def test_different_transitions_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては政治のニュースです。"),
            _make_line("transition", "さて、経済の話題はどうでしょうか。"),
            _make_line("transition", "話は変わりまして、スポーツのニュースをどうぞ。"),
        ]
        errors = lint_script(lines)
        trans_errors = [e for e in errors if "[TRANS_VARIATION]" in e]
        assert len(trans_errors) == 0

    def test_similar_transitions_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては政治のニュースです。"),
            _make_line("transition", "続いては経済のニュースです。"),
        ]
        errors = lint_script(lines)
        trans_errors = [e for e in errors if "[TRANS_VARIATION]" in e]
        assert len(trans_errors) == 1
        assert "類似度" in trans_errors[0]

    def test_single_transition_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては政治のニュースです。"),
        ]
        errors = lint_script(lines)
        trans_errors = [e for e in errors if "[TRANS_VARIATION]" in e]
        assert len(trans_errors) == 0

    def test_no_transitions_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
        ]
        errors = lint_script(lines)
        trans_errors = [e for e in errors if "[TRANS_VARIATION]" in e]
        assert len(trans_errors) == 0

    def test_identical_transitions_raises_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては政治のニュースです。"),
            _make_line("transition", "続いては政治のニュースです。"),
        ]
        errors = lint_script(lines)
        trans_errors = [e for e in errors if "[TRANS_VARIATION]" in e]
        assert len(trans_errors) == 1


class TestTransitionContextCheck:
    """ルール5: transitionコンテキストチェック [TRANS_CONTEXT] (ERROR)"""

    def test_with_bridges_no_generic_text_no_error(self):
        from app.batch.generate_script import lint_script

        bridges = [{"from_topic": "政治", "to_topic": "経済", "bridge": "政治から経済へ"}]
        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "政治の動きを追った後は、経済の状況を見ていきましょう。"),
            _make_line("transition", "では、為替市場の詳細に入ります。"),
        ]
        errors = lint_script(lines, bridges=bridges)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 0

    def test_with_bridges_next_topic_in_transition_raises_error(self):
        from app.batch.generate_script import lint_script

        bridges = [{"from_topic": "政治", "to_topic": "経済", "bridge": "政治から経済へ"}]
        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "政治の動きを追った後は、経済の状況を見ていきましょう。"),
            _make_line("transition", "次の話題は経済です。"),
        ]
        errors = lint_script(lines, bridges=bridges)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 1
        assert "汎用表記" in ctx_errors[0]

    def test_no_bridges_rule_disabled_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次の話題は経済です。"),
        ]
        errors = lint_script(lines)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 0

    def test_bridges_none_rule_disabled_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次の話題は経済です。"),
        ]
        errors = lint_script(lines, bridges=None)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 0

    def test_bridges_empty_list_rule_disabled_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次の話題は経済です。"),
        ]
        errors = lint_script(lines, bridges=[])
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 0

    @pytest.mark.parametrize("generic_text", [
        "次の話題は環境問題についてです。",
        "次のトピックは環境問題です。",
        "続いては環境問題のニュースです。",
        "次は経済の話題です。",
        "では次のトピックに移ります。",
    ])
    def test_various_generic_expressions_detected(self, generic_text):
        from app.batch.generate_script import lint_script

        bridges = [{"from_topic": "政治", "to_topic": "環境", "bridge": "政治から環境へ"}]
        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "政治の動きを追った後は、経済の状況を見ていきましょう。"),
            _make_line("transition", generic_text),
        ]
        errors = lint_script(lines, bridges=bridges)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 1

    def test_first_transition_skipped_even_if_generic(self):
        """最初のtransition行はコンテキストチェックの対象外（beforeに何もない）"""
        from app.batch.generate_script import lint_script

        bridges = [{"from_topic": "政治", "to_topic": "経済", "bridge": "政治から経済へ"}]
        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次の話題は経済です。"),
        ]
        errors = lint_script(lines, bridges=bridges)
        ctx_errors = [e for e in errors if "[TRANS_CONTEXT]" in e]
        assert len(ctx_errors) == 0


class TestExistingLintRulesRegression:
    """回帰テスト: 既存のlintルールが引き続き動作すること"""

    def test_forbidden_phrases_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "ここで大事なのは、背景ですよね", speaker="male"),
        ]
        errors = lint_script(lines)
        phrase_errors = [e for e in errors if "禁止フレーズ" in e]
        assert len(phrase_errors) == 1

    def test_no_forbidden_phrases_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "今日の重要なニュースをお伝えします。", speaker="male"),
        ]
        errors = lint_script(lines)
        phrase_errors = [e for e in errors if "禁止フレーズ" in e]
        assert len(phrase_errors) == 0

    def test_duplicate_text_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "同じテキストです。"),
            _make_line("news", "同じテキストです。"),
        ]
        errors = lint_script(lines)
        dup_errors = [e for e in errors if "テキストが重複" in e]
        assert len(dup_errors) == 1

    def test_catchphrase_repetition_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "一見シンプルに見えますが、実は構造的な問題があります"),
            _make_line("news", "一見シンプルに見えますが、実は構造的な問題があります"),
        ]
        errors = lint_script(lines)
        catchphrase_errors = [e for e in errors if "口癖" in e]
        assert len(catchphrase_errors) == 1

    def test_requires_digits_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "数字で見ると分かるんですけど、これは大きな問題です。"),
        ]
        errors = lint_script(lines)
        digit_errors = [e for e in errors if "数字" in e]
        assert len(digit_errors) == 1

    def test_requires_digits_with_digits_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "数字で見ると分かるんですけど、50%の人が支持しています。"),
        ]
        errors = lint_script(lines)
        digit_errors = [e for e in errors if "数字" in e]
        assert len(digit_errors) == 0

    def test_article_id_reference_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "記事123の内容についてお伝えします。"),
        ]
        errors = lint_script(lines)
        id_errors = [e for e in errors if "記事ID" in e]
        assert len(id_errors) == 1

    def test_no_article_id_reference_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "この記事の内容についてお伝えします。"),
        ]
        errors = lint_script(lines)
        id_errors = [e for e in errors if "記事ID" in e]
        assert len(id_errors) == 0

    def test_discussion_after_news_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "ニュース1", article_id=1),
            _make_line("transition", "では次の話題です。"),
            _make_line("discussion", "今日の話題を振り返ります。"),
        ]
        errors = lint_script(lines)
        discussion_errors = [e for e in errors if "discussion" in e]
        assert len(discussion_errors) == 0

    def test_discussion_before_news_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("discussion", "今日の話題を振り返ります。"),
            _make_line("news", "ニュース1", article_id=1),
        ]
        errors = lint_script(lines)
        discussion_errors = [e for e in errors if "discussion" in e]
        assert len(discussion_errors) == 1


class TestTransitionTruncatedCheck:
    """TRUNCATED_TRANS: transition行の不完全チェック (WARN)"""

    def test_complete_transition_no_warning(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては政治のニュースです。"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 0

    def test_transition_ending_with_ellipsis_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "いったい何のための戦争だったのか……"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 1
        assert "不完全な文" in trunc_errors[0]

    def test_transition_too_short_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 1
        assert "短すぎます" in trunc_errors[0]

    def test_non_transition_section_with_ellipsis_ignored(self):
        """news行の「……」は対象外"""
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "これは重要な問題です……今後も注視します。"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 0

    def test_transition_with_ellipsis_mid_sentence_no_warning(self):
        """「……」が文中にあるだけなら不完全とは判定しない"""
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "さて、本題に入る前に……ちょっと寄り道です。"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 0

    def test_transition_exactly_five_chars_no_warning(self):
        """5文字以上ならWARNにならない"""
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次の話題へ"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 0

    def test_transition_four_chars_warns(self):
        """4文字以下はWARN"""
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "次へ"),
        ]
        errors = lint_script(lines)
        trunc_errors = [e for e in errors if "[TRUNCATED_TRANS]" in e]
        assert len(trunc_errors) == 1


class TestPlaceholderBracketCheck:
    """全角ブラケット〔...〕（U+3014/U+3015）検出ルールのテスト"""

    def test_news_with_bracket_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "〔トピックA〕の内容についてお伝えします。"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 1

    def test_discussion_with_bracket_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("discussion", "〔discussion 発言〕"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 1

    def test_transition_with_bracket_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("transition", "続いては〔トピックA〕のニュースです。"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 1

    def test_intro_with_bracket_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。〔一言〕"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 1

    def test_clean_text_no_error(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("news", "OpenAIが最新モデルを公開しました。"),
            _make_line("discussion", "今回の発表は競合他社の動きも活発な中での発表です。"),
            _make_line("transition", "では次は気候変動の話題をご紹介します。"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 0

    def test_outro_with_bracket_detected(self):
        from app.batch.generate_script import lint_script

        lines = [
            _make_line("intro", "「ニュースのとなり」の時間です。"),
            _make_line("outro", "本日のニュースは以上です。〔総括〕"),
        ]
        errors = lint_script(lines)
        bracket_errors = [e for e in errors if "プレースホルダー表記" in e]
        assert len(bracket_errors) == 1
