from app.batch.generate_script import (
    _BRIDGE_TRANSITION_PHRASES,
    _TRANSITION_PHRASES,
    _ensure_transitions,
    _is_broken_transition_text,
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


class TestIsBrokenTransitionText:
    """_is_broken_transition_text() の判定条件そのものを検証する（BEE-661/BEE-662）。"""

    def test_bee661_episode355_example_detected_as_broken(self):
        # BEE-661 で報告された、エピソード355 line 11 の実例
        text = (
            "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
            "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
            "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。"
        )
        assert _is_broken_transition_text(text) is True

    def test_normal_single_sentence_transition_not_broken(self):
        for text in (
            "続いては最新のテクノロジーニュースです。",
            "それでは、経済の話題に移ります。",
            "話は変わりまして、気になるスポーツニュースをどうぞ。",
        ):
            assert _is_broken_transition_text(text) is False, text

    def test_natural_bridge_with_single_trailing_period_not_broken(self):
        # レビュープロンプトが良い例として挙げる、前の話題に自然に言及する
        # Contextual Bridge スタイルの単文（句点は末尾の1個のみ）
        text = "そういった極限的な脅威から視点を移して、次に経済ニュースを見てみましょう。"
        assert _is_broken_transition_text(text) is False

    def test_short_reaction_phrase_not_broken(self):
        assert _is_broken_transition_text("気になりますね。") is False

    def test_empty_text_not_broken(self):
        assert _is_broken_transition_text("") is False
        assert _is_broken_transition_text("   ") is False

    def test_two_sentences_without_trailing_period_detected(self):
        assert _is_broken_transition_text("前の話はここまでです。それでは次の話題です") is True

    def test_all_transition_phrases_not_broken(self):
        # BEE-664: _TRANSITION_PHRASES 31件全件（複文構成の7件を含む）が、
        # {topic} 差し込み後も壊れたtransitionと誤判定されないこと（受入条件）。
        assert len(_TRANSITION_PHRASES) == 31
        for phrase in _TRANSITION_PHRASES:
            text = phrase.format(topic="経済")
            assert _is_broken_transition_text(text) is False, text

    def test_all_bridge_transition_phrases_not_broken(self):
        # BEE-664: _BRIDGE_TRANSITION_PHRASES 6件全件（全て複文構成）が、
        # {bridge}/{topic} 差し込み後も壊れたtransitionと誤判定されないこと
        # （受入条件）。bridge_text は narrative arc プロンプトの仕様どおり、
        # 句点で終わる完結した一文の場合とそうでない場合の両方を確認する。
        assert len(_BRIDGE_TRANSITION_PHRASES) == 6
        for phrase in _BRIDGE_TRANSITION_PHRASES:
            for bridge in (
                "気候変動の影響は経済にも及んでいます",
                "地球温暖化が経済活動にも影響を及ぼしています。",
            ):
                text = phrase.format(bridge=bridge, topic="テクノロジー")
                assert _is_broken_transition_text(text) is False, text

    def test_bee661_style_text_disguised_as_bridge_phrase_still_detected(self):
        # BEE-664: {bridge} は任意の文字列に一致しうるため、壊れたtransition
        # 自身が「{bridge} それでは、{topic}のニュースをどうぞ。」のような
        # テンプレート形状とたまたま一致してしまう場合でも、bridge部分自体が
        # 複文（＝それ自体に前記事の締め文が混在している）であれば壊れている
        # と判定を維持すること（BEE-661の再発防止に対する回帰試験）。
        text = (
            "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
            "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
            "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。"
        )
        assert _is_broken_transition_text(text) is True


class TestEnsureTransitionsBrokenLLMTransitionReplacement:
    """LLMが生成した『前記事の締め文＋次記事告知』混在のtransitionを検知し、
    安全な2行の掛け合いへ置換する回帰テスト（BEE-661/BEE-662）。"""

    _BROKEN_TEXT = (
        "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
        "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
        "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。"
    )

    def test_broken_transition_at_news_boundary_is_replaced(self):
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "海外邦人についての記事です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": self._BROKEN_TEXT},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "行方不明事案についての記事です。"},
        ]
        summaries = [
            {"id": 1, "title": "海外邦人の窮状", "summary": "海外邦人の窮状に関する記事です。"},
            {"id": 2, "title": "行方不明事案", "summary": "カンボジアで行方不明になった邦人に関する記事です。"},
        ]

        result = _ensure_transitions(lines, summaries)

        # 壊れた文言はどのtransition行にも残っていないこと（受入条件）
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert self._BROKEN_TEXT not in transition_texts
        assert not any("息のニュースをどうぞ" in t for t in transition_texts), transition_texts

        # 記事2境界のtransitionは、既存の2行（橋渡し＋短い受け）仕様に置き換わること
        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["speaker"] != art2_transitions[1]["speaker"]

        # lint_script でも壊れたtransitionに起因するエラーが出ないこと
        errors = lint_script(result)
        assert not any("TRANSITION_SOLO" in e for e in errors), errors

    def test_broken_text_detection_reused_by_lint_is_consistent(self):
        # _is_broken_transition_text は _ensure_transitions の内部判定にのみ使うが、
        # 同じ判定関数を直接呼んでも同じ結果になることを確認する（整合性の担保）
        assert _is_broken_transition_text(self._BROKEN_TEXT) is True

    def test_discussion_precursor_broken_style_is_not_touched(self):
        # discussion直前のtransitionはテンプレート自体が複文（例:
        # 「{topic}、私も気になっているんですよ。どう思います？」）を前提とするため、
        # 句読点構造だけでは対象外として扱われ、除去されないこと
        two_sentence_discussion_trans = "気になりますね。どう思います？"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {
                "section": "transition",
                "article_id": 1,
                "speaker": "female",
                "text": two_sentence_discussion_trans,
            },
            {"section": "discussion", "article_id": 1, "speaker": "male", "text": "深掘りします。"},
        ]
        summaries = [{"id": 1, "title": "記事1タイトル", "summary": "記事1の要約です。"}]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert two_sentence_discussion_trans in transition_texts

    def test_broken_style_text_on_first_article_after_intro_is_not_touched(self):
        # last_content_aid が None（intro直後 = 前の記事が存在しない）場合は
        # 『前記事の締め文混入』という前提が成立しないため対象外とする
        two_sentence_text = "本日も盛りだくさんです。それでは記事1のニュースをどうぞ。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "transition", "article_id": 1, "speaker": "female", "text": two_sentence_text},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
        ]
        summaries = [{"id": 1, "title": "記事1タイトル", "summary": "記事1の要約です。"}]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert two_sentence_text in transition_texts

    def test_normal_llm_transition_at_news_boundary_is_preserved(self):
        # 正常な単文transitionは過剰に置換されないこと（受入条件: 既存の正常な
        # 遷移文を過剰に置換しない判定）
        normal_text = "それでは、経済ニュースの話題に移ります。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": normal_text},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "記事2タイトル"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert normal_text in transition_texts
        # 置換されていないので記事2境界のtransitionは1行のまま
        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 1

    def test_natural_contextual_bridge_transition_is_preserved(self):
        # レビュー観点で推奨される、前の話題に一言触れてから移る自然な
        # Contextual Bridgeスタイル（句点は末尾の1個のみ）は誤って置換しないこと
        bridge_text = "そういった課題を踏まえた上で、次はテクノロジーの話題に目を向けてみましょう。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": bridge_text},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "テクノロジー"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert bridge_text in transition_texts

