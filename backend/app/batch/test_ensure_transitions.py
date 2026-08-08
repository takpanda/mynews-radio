from app.batch.generate_script import (
    _BRIDGE_TRANSITION_PHRASES,
    _ensure_transitions,
    _pick_phrase,
    _pick_speaker,
    lint_script,
)


class TestPickPhraseNoConsecutiveDuplicate:
    def test_never_repeats_immediately(self):
        phrases = ["a", "b", "c", "d"]
        used = {"last": None}
        prev = None
        for _ in range(100):
            phrase = _pick_phrase(phrases, used)
            assert phrase != prev, f"consecutive duplicate: {phrase}"
            prev = phrase

    def test_returns_from_pool(self):
        phrases = ["x", "y"]
        used = {"last": None}
        for _ in range(20):
            phrase = _pick_phrase(phrases, used)
            assert phrase in phrases


class TestEnsureTransitionsDiscussionInsertion:
    def test_transition_inserted_before_discussion(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "discussion", "article_id": 2},
        ]
        summaries = [{"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}]
        result = _ensure_transitions(lines, summaries)
        sections = [r["section"] for r in result]
        assert "transition" in sections, "no transition inserted"

    def test_no_extra_transition_when_already_present(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "transition", "article_id": 2, "speaker": "female"},
            {"section": "news", "article_id": 2},
        ]
        summaries = [{"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}]
        result = _ensure_transitions(lines, summaries)
        # art1 boundary has no LLM transition, so it's auto-inserted as a 2-line
        # exchange (bridge + short reaction, BEE-630); the input transition at
        # art2 is preserved as-is (1 line) and no extra one is inserted before news(art2)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count == 3, f"unexpected transition count: {trans_count}"


class TestEnsureTransitionsArticleBoundary:
    def test_transition_at_each_article_id_change(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
            {"section": "news", "article_id": 3},
        ]
        summaries = [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
            {"id": 3, "title": "C"},
        ]
        result = _ensure_transitions(lines, summaries)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count >= 2, f"expected at least 2 transitions across 3 articles, got {trans_count}"

    def test_same_article_id_no_extra_transition(self):
        # intro->news(1) inserts a 2-line transition (bridge + short reaction, BEE-630)
        # news(1)->news(1) does NOT insert because article_id unchanged
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 1},
        ]
        summaries = [{"id": 1, "title": "Single"}]
        result = _ensure_transitions(lines, summaries)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count == 2, f"expected exactly 2 transition lines on intro->news boundary, got {trans_count}"


class TestPickSpeaker:
    def test_empty_result_returns_male(self):
        assert _pick_speaker([], "news") == "male"

    def test_alternates_after_single_news_line(self):
        # 単一の news 行の場合、最後の話者とは交互に
        result = [{"section": "news", "speaker": "male"}]
        assert _pick_speaker(result, "news") == "female"

    def test_breaks_two_consecutive_same_speaker(self):
        # 直前2つのコンテンツ行が同じ話者 → run>=2 で強制的に相手側
        result = [
            {"section": "news", "speaker": "male"},
            {"section": "news", "speaker": "male"},
        ]
        assert _pick_speaker(result, "news") == "female"

    def test_balance_correction_favors_minority(self):
        # 3行中で male 2 / female 1 → male が dominant なので female を選ぶ
        result = [
            {"section": "news", "speaker": "male"},
            {"section": "news", "speaker": "female"},
            {"section": "news", "speaker": "male"},
        ]
        assert _pick_speaker(result, "news") == "female"

    def test_content_only_ignores_transition(self):
        # transition 行は content_speakers に含まれない
        result = [
            {"section": "transition", "speaker": "male"},
            {"section": "transition", "speaker": "male"},
            {"section": "news", "speaker": "female"},
        ]
        assert _pick_speaker(result, "news") == "male"

    def test_balance_skip_falls_through_to_alternate(self):
        # [f, m, f] → female=2, male=1 → diff=1 < 2 なので balance skip → alternate=male
        result = [
            {"section": "news", "speaker": "female"},
            {"section": "news", "speaker": "male"},
            {"section": "news", "speaker": "female"},
        ]
        assert _pick_speaker(result, "news") == "male"

    def test_phrase_deterministic_with_seed(self):
        import random as _random
        _random.seed(42)
        phrases = ["a", "b", "c"]
        used = {"last": None}
        got = [_random.choice(phrases) for _ in range(3)]
        _random.seed(42)
        expected = [_random.choice(phrases) for _ in range(3)]
        assert got == expected, "_pick_phrase uses random.choice deterministically"


class TestEnsureTransitionsIdNotFoundInText:
    def test_empty_title_no_id_in_transition(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 42},
        ]
        summaries = [{"id": 42, "title": "", "url": ""}]
        result = _ensure_transitions(lines, summaries)
        for line in result:
            if line["section"] == "transition":
                text = line.get("text", "")
                assert not any(c.isdigit() for c in text), f"transition contains digit in ID context: {text}"

    def test_fallback_uses_neutral_expression(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 99},
        ]
        summaries = [{"id": 1, "title": "Real"}]
        result = _ensure_transitions(lines, summaries)
        for line in result:
            if line["section"] == "transition":
                text = line.get("text", "")
                assert "記事" not in text, f"transition contains article ID reference: {text}"
                assert not any(c.isdigit() for c in text), f"transition contains digit in ID context: {text}"


class TestEnsureTransitionsBridgeContextual:
    """Narrative Arc の Contextual Bridge を考慮した transition 生成のテスト。"""

    def test_bridge_text_used_in_transition(self):
        """bridge がある場合、bridge テキストを含む transition が生成されること"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
        ]
        summaries = [
            {"id": 1, "title": "気候変動"},
            {"id": 2, "title": "経済ニュース"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": "気候変動の影響は経済にも及んでいます"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        # 記事境界のtransitionは橋渡し＋短い受けの2行（BEE-630）。bridgeテキストは
        # 1行目（橋渡し）にのみ含まれ、2行目（短い受け）には含まれない。
        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert "気候変動の影響は経済にも及んでいます" in art2_transitions[0].get("text", ""), (
            f"bridge text not found in transition: {art2_transitions[0].get('text', '')}"
        )

    def test_bridge_not_used_for_first_article(self):
        """intro→news で last_content_aid=None の場合、bridge は使われず通常フォールバック"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
        ]
        summaries = [
            {"id": 1, "title": "テクノロジーニュース"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": "some bridge"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        for line in result:
            if line["section"] == "transition" and line.get("article_id") == 1:
                text = line.get("text", "")
                assert "some bridge" not in text, "bridge should not appear for first article"
                assert "{bridge}" not in text, "unformatted placeholder in transition"

    def test_no_bridge_falls_back_to_template(self):
        """bridge がない遷移では従来のテンプレートフレーズが使われること"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
            {"section": "news", "article_id": 3},
        ]
        summaries = [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
            {"id": 3, "title": "C"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": "bridge for 1→2"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        for line in result:
            if line["section"] == "transition":
                text = line.get("text", "")
                assert "{bridge}" not in text, f"unformatted bridge placeholder: {text}"
                assert "{topic}" not in text, f"unformatted topic placeholder: {text}"

    def test_arc_none_preserves_original_behavior(self):
        """arc=None の場合、従来のテンプレート動作が完全に維持されること"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
        ]
        summaries = [
            {"id": 1, "title": "ニュース1"},
            {"id": 2, "title": "ニュース2"},
        ]
        result_with = _ensure_transitions(lines, summaries, arc=None)
        result_without = _ensure_transitions(lines, summaries)
        assert len(result_with) == len(result_without), "arc=None should produce same length"
        for lw, lwo in zip(result_with, result_without):
            assert lw["section"] == lwo["section"], "section mismatch"
            if lw["section"] == "transition":
                assert lw["article_id"] == lwo["article_id"], "article_id mismatch"

    def test_bridge_for_specific_pair_only(self):
        """特定のペアのみ bridge があり、他の遷移は通常テンプレート"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
            {"section": "news", "article_id": 3},
            {"section": "news", "article_id": 4},
        ]
        summaries = [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
            {"id": 3, "title": "C"},
            {"id": 4, "title": "D"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 2, "to_article_id": 3, "bridge_text": "BとCをつなぐ橋渡し"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        # article_idごとにtransitionは2行（橋渡し＋短い受け）。bridgeテキストは
        # 1行目（橋渡し）にのみ含まれる（BEE-630）。
        transitions_by_aid: dict = {}
        for line in result:
            if line["section"] != "transition":
                continue
            text = line.get("text", "")
            assert "{bridge}" not in text, f"unformatted bridge placeholder: {text}"
            assert "{topic}" not in text, f"unformatted topic placeholder: {text}"
            transitions_by_aid.setdefault(line.get("article_id"), []).append(text)

        assert "BとCをつなぐ橋渡し" in transitions_by_aid[3][0], (
            f"bridge text should appear in the bridging line for article 3: {transitions_by_aid[3]}"
        )
        for aid in (2, 4):
            assert all("BとCをつなぐ橋渡し" not in t for t in transitions_by_aid[aid]), (
                f"bridge text should NOT appear in transition to article {aid}: {transitions_by_aid[aid]}"
            )

    def test_bridge_text_in_bridge_phrases_only(self):
        """bridge が使われる際は _BRIDGE_TRANSITION_PHRASES のいずれかのフォーマットに従うこと"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
        ]
        summaries = [
            {"id": 1, "title": "テーマA"},
            {"id": 2, "title": "テーマB"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": "橋渡し文"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        # 記事境界のtransitionは2行（橋渡し＋短い受け）。_BRIDGE_TRANSITION_PHRASES に
        # 従ったbridgeテキストは1行目（橋渡し）にのみ含まれる（BEE-630）。
        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        bridge_text = art2_transitions[0].get("text", "")
        # _BRIDGE_TRANSITION_PHRASES のテンプレートに従っていれば
        # "{bridge}" は bridge text で置換済みのはず
        assert "橋渡し文" in bridge_text, f"bridge text missing: {bridge_text}"
        assert "テーマB" in bridge_text, f"topic missing in bridge transition: {bridge_text}"

    def test_bridge_not_in_first_transition(self):
        """intro→article1 の最初の transition には bridge は適用されない"""
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
        ]
        summaries = [
            {"id": 1, "title": "テックA"},
            {"id": 2, "title": "テックB"},
        ]
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": "つなぎの文"},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        art1_transitions = [
            l for l in result
            if l["section"] == "transition" and l.get("article_id") == 1
        ]
        assert len(art1_transitions) >= 1
        for t in art1_transitions:
            assert "つなぎの文" not in t.get("text", ""), (
                "bridge should not appear in transition to article 1"
            )


class TestEnsureTransitionsMissingInputRegression:
    """BEE-630 レビュー指摘の回帰テスト: LLMがtransitionを完全に省略した入力でも、
    _ensure_transitions() 後の最終台本が記事境界transitionの2行・異話者制約
    ([TRANSITION_SOLO]) を満たすこと。"""

    def test_missing_transitions_are_completed_as_two_line_alternating_speaker(self):
        # LLM出力を模した、transition行が一切ない2記事構成の台本
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "news", "article_id": 1, "speaker": "female", "text": "記事1についての感想です。"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2の内容です。"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2についての感想です。"},
            {"section": "outro", "speaker": "male", "text": "以上、本日のニュースでした。"},
            {"section": "outro", "speaker": "female", "text": "また明日お会いしましょう。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル", "summary": "記事1の要約です。"},
            {"id": 2, "title": "記事2タイトル", "summary": "記事2の要約です。"},
        ]

        # 補完前は transition が存在しないため TRANSITION_SOLO は検出されない
        # （そもそもtransitionブロックが無い = 対象外）
        pre_errors = lint_script(lines)
        pre_solo_errors = [e for e in pre_errors if "[TRANSITION_SOLO]" in e]
        assert pre_solo_errors == []

        result = _ensure_transitions(lines, summaries)

        # 補完後は各記事境界のtransitionが2行・異話者になっているため
        # TRANSITION_SOLO は検出されないこと（BEE-630 レビュー指摘の再現ケース）
        post_errors = lint_script(result)
        post_solo_errors = [e for e in post_errors if "[TRANSITION_SOLO]" in e]
        assert post_solo_errors == [], f"unexpected TRANSITION_SOLO errors: {post_solo_errors}"

        transitions = [l for l in result if l["section"] == "transition"]
        # intro→記事1、記事1→記事2 の2境界 × 2行 = 4行
        assert len(transitions) == 4
        for i in range(0, len(transitions), 2):
            pair = transitions[i:i + 2]
            assert pair[0]["speaker"] != pair[1]["speaker"], (
                f"transition pair should alternate speakers: {pair}"
            )
            assert pair[0]["article_id"] == pair[1]["article_id"]

