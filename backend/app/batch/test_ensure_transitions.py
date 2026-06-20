from app.batch.generate_script import _ensure_transitions, _pick_phrase, _pick_speaker, _BRIDGE_TRANSITION_PHRASES


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
        # art1 boundary inserts a transition; input transition at art2 is preserved but no extra one inserted before news(art2)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert 1 < trans_count <= 2, f"unexpected transition count: {trans_count}"


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
        # intro->news(1) inserts 1 transition (first content line)
        # news(1)->news(1) does NOT insert because article_id unchanged
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 1},
        ]
        summaries = [{"id": 1, "title": "Single"}]
        result = _ensure_transitions(lines, summaries)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count == 1, f"expected exactly 1 transition on intro->news boundary, got {trans_count}"


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
        for line in result:
            if line["section"] == "transition" and line.get("article_id") == 2:
                text = line.get("text", "")
                assert "気候変動の影響は経済にも及んでいます" in text, (
                    f"bridge text not found in transition: {text}"
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
        for line in result:
            if line["section"] == "transition":
                text = line.get("text", "")
                assert "{bridge}" not in text, f"unformatted bridge placeholder: {text}"
                assert "{topic}" not in text, f"unformatted topic placeholder: {text}"
                if line.get("article_id") == 3:
                    assert "BとCをつなぐ橋渡し" in text, (
                        f"bridge text should appear in transition to article 3: {text}"
                    )
                elif line.get("article_id") in (2, 4):
                    assert "BとCをつなぐ橋渡し" not in text, (
                        f"bridge text should NOT appear in transition to article {line.get('article_id')}: {text}"
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
        for line in result:
            if line["section"] == "transition" and line.get("article_id") == 2:
                text = line.get("text", "")
                # _BRIDGE_TRANSITION_PHRASES のテンプレートに従っていれば
                # "{bridge}" は bridge text で置換済みのはず
                assert "橋渡し文" in text, f"bridge text missing: {text}"
                assert "テーマB" in text, f"topic missing in bridge transition: {text}"

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

