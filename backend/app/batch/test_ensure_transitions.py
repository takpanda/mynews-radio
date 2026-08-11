from app.batch.generate_script import (
    _BRIDGE_TRANSITION_PHRASES,
    _TRANSITION_PHRASES,
    _ensure_transitions,
    _is_broken_transition_text,
    _is_usable_bridge_text,
    _pick_phrase,
    _pick_speaker,
    _safe_topic_from_title,
    _strip_trailing_particle,
    _truncate_topic_at_boundary,
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

    def test_generic_two_sentence_lead_in_not_broken(self):
        # BEE-672 レビュー指摘: 既知テンプレート外でも、前の記事の内容に
        # 触れない短い繋ぎ語（続いて/それでは/等）で始まる自然な2文構成の
        # transitionは壊れたtransitionと誤判定しないこと
        assert _is_broken_transition_text("続いて経済ニュースです。詳しく見ていきましょう。") is False

    def test_two_sentence_lead_in_with_long_first_sentence_still_broken(self):
        # 繋ぎ語で始まっていても、1文目が長く前の記事の具体的な内容を
        # 語っている可能性が高い場合は、引き続き壊れたtransitionとみなす
        text = (
            "それでは、先ほどの記事で紹介した制度の不備と組織への恐怖の話は"
            "ここで一区切りにしましょう。次は経済ニュースです。"
        )
        assert _is_broken_transition_text(text) is True

    def test_three_sentence_lead_in_still_broken(self):
        # 繋ぎ語で始まっていても、文が3つ以上ある場合は対象外（2文構成の
        # 例外は適用しない）
        text = "続いて経済ニュースです。詳しく見ていきましょう。楽しみですね。"
        assert _is_broken_transition_text(text) is True

    def test_short_backward_reference_lead_in_still_broken(self):
        # BEE-672 再指摘: 「繋ぎ語で始まる／2文／1文目20文字以内」という
        # 形状だけでは、短い前記事内容の混在（例:「続いて前の記事の結論
        # です。次は経済ニュースです。」）を排除できない。前の記事を要約・
        # 振り返る表現を含む場合は、1文目が短くても引き続き壊れたtransition
        # とみなすこと（CodeReviewerが再現した誤許容ケース）
        text = "続いて前の記事の結論です。次は経済ニュースです。"
        assert _is_broken_transition_text(text) is True

    def test_short_backward_reference_variants_still_broken(self):
        # 「結論」以外の後方参照表現でも同様に検出されること
        texts = [
            "それでは、先ほどの話はここまでです。次は経済ニュースです。",
            "続いて、前の話をまとめると以上です。次は経済ニュースです。",
            "では、前のニュースを振り返っておきましょう。次は経済ニュースです。",
        ]
        for text in texts:
            assert _is_broken_transition_text(text) is True, text

    def test_backward_reference_word_in_second_sentence_not_broken(self):
        # CodeReviewer再指摘(BEE-672): 後方参照マーカー（「まとめ」等）が
        # 2文目（次の話題の具体的な内容を説明する文）に含まれるだけでは、
        # 前の記事の内容が混在しているとは限らない。「市場の動きをまとめて
        # 確認しましょう」は次の話題（経済ニュース）についての説明であり、
        # 前の記事を要約・振り返っているわけではないため、壊れたtransition
        # と誤判定しないこと
        text = "続いて経済ニュースです。市場の動きをまとめて確認しましょう。"
        assert _is_broken_transition_text(text) is False


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


class TestEnsureTransitionsBrokenFollowedByShortReaction:
    """壊れた遷移文の直後に正常な短い反応行が続くケースの回帰テスト（BEE-672）。

    直前1行だけを検査すると、壊れた遷移文が反応行に隠れて見逃される
    （エピソード360 line 8, 9, 10 に相当する構造）。
    """

    # BEE-671 で報告されたエピソード360の実例（前記事の要約/注記と次記事の
    # 告知が混在し、「H3ロケットでを」のような文法破綻もある）
    _BROKEN_TEXT = (
        "同じH3ロケットとみちびき衛星の成功を、NHKの視点でさらに詳しく解説。"
        "技術の進歩がもたらす未来への期待に焦点を当てる。"
        "ここで視点を変えて、日本版GPS衛星「みちびき7号機」"
        "H3ロケットでを見てみましょう。"
    )

    def test_broken_transition_hidden_behind_short_reaction_is_removed(self):
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "H3ロケットとみちびき衛星についての記事です。"},
            # line 8相当: 壊れたtransition（前記事の要約と次記事告知が混在）
            {"section": "transition", "article_id": 2, "speaker": "female", "text": self._BROKEN_TEXT},
            # line 9相当: 正常な短い反応行（これが直前1行になり、壊れた行を隠す）
            {"section": "transition", "article_id": 2, "speaker": "male", "text": "そうなんですね。"},
            # line 10相当: 次の記事本文
            {"section": "news", "article_id": 2, "speaker": "female", "text": "みちびき7号機についての記事です。"},
        ]
        summaries = [
            {"id": 1, "title": "H3ロケットとみちびき衛星", "summary": "H3ロケットとみちびき衛星の成功に関する記事です。"},
            {"id": 2, "title": "みちびき7号機", "summary": "日本版GPS衛星「みちびき7号機」に関する記事です。"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        # 壊れた遷移文はどのtransition行にも残っていないこと（受入条件）
        assert self._BROKEN_TEXT not in transition_texts
        assert not any("H3ロケットでを" in t for t in transition_texts), transition_texts

        # 記事2境界のtransitionは、既存の2行（橋渡し＋短い受け）仕様で
        # 安全な文に置き換わっていること（両司会者の短い掛け合いが維持される）
        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["speaker"] != art2_transitions[1]["speaker"]
        for t in art2_transitions:
            assert _is_broken_transition_text(t["text"]) is False, t["text"]

        # lint_script でも壊れたtransitionに起因するエラーが出ないこと
        errors = lint_script(result)
        assert not any("TRANSITION_SOLO" in e for e in errors), errors

    def test_multiple_article_boundaries_each_inspected_independently(self):
        # 受入条件: 同じ記事境界に属する複数のtransitionだけでなく、
        # 複数の記事境界がそれぞれ独立して検査対象になること
        second_broken_text = (
            "この話題はここまでにして、次のニュースに移りましょう。それでは、"
            "経済指標の発表についてのニュースをどうぞ。"
        )
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": self._BROKEN_TEXT},
            {"section": "transition", "article_id": 2, "speaker": "male", "text": "そうなんですね。"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
            {"section": "transition", "article_id": 3, "speaker": "male", "text": second_broken_text},
            {"section": "transition", "article_id": 3, "speaker": "female", "text": "気になります。"},
            {"section": "news", "article_id": 3, "speaker": "male", "text": "記事3の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "記事2タイトル"},
            {"id": 3, "title": "記事3タイトル"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert self._BROKEN_TEXT not in transition_texts
        assert second_broken_text not in transition_texts

        for aid in (2, 3):
            blocks = [
                l for l in result if l["section"] == "transition" and l.get("article_id") == aid
            ]
            assert len(blocks) == 2
            assert blocks[0]["speaker"] != blocks[1]["speaker"]


class TestEnsureTransitionsBrokenBehindMismatchedArticleId:
    """CodeReviewer指摘(must #1, BEE-672): 壊れたtransitionの直後に、
    article_idが現在の記事と一致しない短い反応行が続く場合、article_id不一致
    処理が末尾1行だけを削除して prev_is_transition を無条件に False へ落として
    いたため、残った壊れたtransitionがブロック検査の対象から外れて見逃されて
    いた回帰試験。"""

    _BROKEN_TEXT = (
        "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
        "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
        "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。"
    )

    def test_broken_transition_behind_mismatched_article_id_reaction_is_removed(self):
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            # 記事2境界の壊れたtransition（article_idは記事2で正しい）
            {"section": "transition", "article_id": 2, "speaker": "female", "text": self._BROKEN_TEXT},
            # article_idが記事1のまま残った短い反応行（誤帰属）。これが直前
            # 1行になり、先にarticle_id不一致処理で削除されるため、その下に
            # 隠れた壊れたtransitionが見逃されていた
            {"section": "transition", "article_id": 1, "speaker": "male", "text": "そうなんですね。"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル", "summary": "記事1の要約です。"},
            {"id": 2, "title": "行方不明事案", "summary": "カンボジアで行方不明になった邦人に関する記事です。"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        # 壊れた遷移文はどのtransition行にも残っていないこと（受入条件）
        assert self._BROKEN_TEXT not in transition_texts
        assert not any("息のニュースをどうぞ" in t for t in transition_texts), transition_texts
        # article_id不一致だった反応行の文言も残らないこと（ブロックごと
        # 安全な2行に置き換わる）
        assert "そうなんですね。" not in transition_texts

        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["speaker"] != art2_transitions[1]["speaker"]
        for t in art2_transitions:
            assert _is_broken_transition_text(t["text"]) is False, t["text"]

        errors = lint_script(result)
        assert not any("TRANSITION_SOLO" in e for e in errors), errors


class TestEnsureTransitionsNormalComplexLeadInPreserved:
    """CodeReviewer指摘(must #2, BEE-672): 前の記事の内容を含まない正常な
    2文構成のtransition（＋短い反応行のブロック）が、過剰に安全なテンプレート
    文へ置換されないことの回帰試験。"""

    def test_generic_two_sentence_transition_block_is_not_replaced(self):
        normal_text = "続いて経済ニュースです。詳しく見ていきましょう。"
        reaction_text = "楽しみですね。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": normal_text},
            {"section": "transition", "article_id": 2, "speaker": "male", "text": reaction_text},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "経済ニュース"},
        ]

        result = _ensure_transitions(lines, summaries)

        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        # 正常なtransitionブロックはそのまま維持され、置換されないこと
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["text"] == normal_text
        assert art2_transitions[1]["text"] == reaction_text

    def test_next_topic_sentence_with_backward_marker_word_is_not_replaced(self):
        # CodeReviewer再指摘(BEE-672): 後方参照マーカーと同じ語（「まとめ」）を
        # 2文目に含むだけの正常なtransitionが、全文への部分一致によって
        # 誤って置換されないこと
        normal_text = "続いて経済ニュースです。市場の動きをまとめて確認しましょう。"
        reaction_text = "楽しみですね。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {"section": "transition", "article_id": 2, "speaker": "female", "text": normal_text},
            {"section": "transition", "article_id": 2, "speaker": "male", "text": reaction_text},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "経済ニュース"},
        ]

        result = _ensure_transitions(lines, summaries)

        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["text"] == normal_text
        assert art2_transitions[1]["text"] == reaction_text


class TestEnsureTransitionsShortBackwardReferenceStillReplaced:
    """CodeReviewer再指摘(BEE-672): 「繋ぎ語で始まる／2文／1文目20文字以内」
    という形状だけを安全とみなす判定では、「続いて前の記事の結論です。
    次は経済ニュースです。」のような短い前記事内容の混在を見逃す。
    _is_generic_two_sentence_lead_in に追加した後方参照語ガードが
    _ensure_transitions() 経由でも機能し、正常な2文遷移の保持と両立する
    ことを確認する回帰試験。"""

    _SHORT_BACKWARD_REFERENCE_TEXT = "続いて前の記事の結論です。次は経済ニュースです。"

    def test_short_backward_reference_transition_is_replaced(self):
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {
                "section": "transition",
                "article_id": 2,
                "speaker": "female",
                "text": self._SHORT_BACKWARD_REFERENCE_TEXT,
            },
            {"section": "transition", "article_id": 2, "speaker": "male", "text": "楽しみですね。"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "経済ニュース"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        # 短い前記事内容が混在したtransitionは最終台本に残らないこと
        assert self._SHORT_BACKWARD_REFERENCE_TEXT not in transition_texts

        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["speaker"] != art2_transitions[1]["speaker"]
        for t in art2_transitions:
            assert _is_broken_transition_text(t["text"]) is False, t["text"]

    def test_short_backward_reference_and_normal_lead_in_coexist(self):
        # 誤許容ケース（記事2境界）と正常ケース（記事3境界）が同一台本内で
        # それぞれ正しく判定されること（受入条件: 正常な遷移文は不要に
        # 置換されない、かつ壊れた遷移文は確実に検出・置換される）
        normal_text = "続いて経済ニュースです。詳しく見ていきましょう。"
        lines = [
            {"section": "intro", "speaker": "male", "text": "「ニュースのとなり」の時間です。"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1の内容です。"},
            {
                "section": "transition",
                "article_id": 2,
                "speaker": "female",
                "text": self._SHORT_BACKWARD_REFERENCE_TEXT,
            },
            {"section": "transition", "article_id": 2, "speaker": "male", "text": "楽しみですね。"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "記事2の内容です。"},
            {"section": "transition", "article_id": 3, "speaker": "male", "text": normal_text},
            {"section": "transition", "article_id": 3, "speaker": "female", "text": "気になります。"},
            {"section": "news", "article_id": 3, "speaker": "male", "text": "記事3の内容です。"},
        ]
        summaries = [
            {"id": 1, "title": "記事1タイトル"},
            {"id": 2, "title": "経済ニュース"},
            {"id": 3, "title": "テクノロジー"},
        ]

        result = _ensure_transitions(lines, summaries)

        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        # 誤許容ケースは除去され、正常ケースはそのまま保持されること
        assert self._SHORT_BACKWARD_REFERENCE_TEXT not in transition_texts
        assert normal_text in transition_texts

        art3_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 3
        ]
        assert len(art3_transitions) == 2
        assert art3_transitions[0]["text"] == normal_text
        assert art3_transitions[1]["text"] == "気になります。"


class TestTopicParticleStripping:
    """_strip_trailing_particle() の単体テスト（BEE-676: 話題名の末尾が助詞の
    場合に、テンプレート側の助詞と連結して「個別接種にを」のような助詞の
    二重連結が生じるのを防ぐ）。"""

    def test_strips_trailing_ni(self):
        assert _strip_trailing_particle("トランプ氏、3種混合ワクチンを個別接種に") == (
            "トランプ氏、3種混合ワクチンを個別接種"
        )

    def test_strips_trailing_wo(self):
        assert _strip_trailing_particle("市場の動きを") == "市場の動き"

    def test_no_trailing_particle_unchanged(self):
        assert _strip_trailing_particle("気候変動") == "気候変動"

    def test_does_not_strip_below_minimum_length(self):
        # 助詞除去後に空文字にはしない（短すぎる場合は元の助詞を残す）
        assert _strip_trailing_particle("を") == "を"


class TestTopicBoundaryTruncation:
    """_truncate_topic_at_boundary() / _safe_topic_from_title() の単体テスト
    （BEE-676: 25文字などの固定位置での切り詰めが「事実があっ」「口から
    吐き出」のような語中切断を生んでいた問題への対策）。"""

    def test_short_text_returned_as_is(self):
        assert _truncate_topic_at_boundary("短いタイトル") == "短いタイトル"

    def test_truncates_at_boundary_char_within_max_len(self):
        # 「、」の直後で安全に切れること（語の途中では切らない）
        text = "日本版GPS衛星みちびき7号機とH3ロケット、打ち上げ成功についての詳細な解説記事です"
        result = _truncate_topic_at_boundary(text)
        assert result == "日本版GPS衛星みちびき7号機とH3ロケット"
        assert len(result) <= 25

    def test_no_boundary_within_max_len_returns_none(self):
        # 区切り文字が25文字以内に無い場合は、語中切断を避けるためNoneを返す
        text = "イオン系列店舗で発生した避難誘導トラブルに関する詳細報告、一時入館を認めた事実があった"
        assert _truncate_topic_at_boundary(text) is None

    def test_safe_topic_from_title_falls_back_when_no_boundary(self):
        # 切り詰めが語中切断になる場合は、不完全な話題名ではなく汎用語へ
        # フォールバックすること（受入条件）
        text = "イオン系列店舗で発生した避難誘導トラブルに関する詳細報告、一時入館を認めた事実があった"
        assert _safe_topic_from_title(text) == "次の話題"

    def test_safe_topic_from_title_empty_returns_generic(self):
        assert _safe_topic_from_title("") == "次の話題"


class TestBridgeTextQualityGate:
    """_is_usable_bridge_text() の単体テスト（BEE-676: 既知テンプレートの
    形状に一致していても、bridge_text が読み上げに適さない冗長な分析文で
    あれば安全な通常テンプレートへフォールバックさせるための品質判定）。"""

    def test_short_single_sentence_is_usable(self):
        assert _is_usable_bridge_text("気候変動の影響は経済にも及んでいます") is True

    def test_short_single_sentence_with_period_is_usable(self):
        assert _is_usable_bridge_text("地球温暖化が経済活動にも影響を及ぼしています。") is True

    def test_empty_bridge_text_not_usable(self):
        assert _is_usable_bridge_text("") is False
        assert _is_usable_bridge_text(None) is False

    def test_verbose_analytical_bridge_text_not_usable(self):
        # エピソード362で確認された「Aの〜から、Bの〜へ。」型の分析的な
        # メタ注記は、単文ではあるが冗長すぎるため読み上げ用として使わない
        text = (
            "トランプ氏の極秘移動が示す「安全への過度な警戒」から、"
            "ワクチン義務の変更という「管理された秩序」へ。"
        )
        assert _is_usable_bridge_text(text) is False

    def test_multi_sentence_bridge_text_not_usable(self):
        # 前記事の要約と分析的注記が複数文にまたがって混在するケース
        text = (
            "家庭内の混乱が、企業の安全対策という「大規模な現場管理」の失敗へとつながる。"
            "理想の避難計画と現実の混乱。"
        )
        assert _is_usable_bridge_text(text) is False

    def test_short_analytical_contrast_bridge_text_not_usable(self):
        # CodeReviewer must指摘(BEE-676): 40文字以下・単文であっても、
        # 「安全への警戒から、秩序の変化へ。」のような「Aの〜から、Bの〜へ」
        # 型の分析的な対比表現は、文字数・単文チェックだけでは弾けない。
        # このような短い分析的メタ注記も読み上げ用として使わないこと。
        text = "安全への警戒から、秩序の変化へ。"
        assert len(text) < 40
        assert _is_usable_bridge_text(text) is False

    def test_short_analytical_contrast_bridge_text_without_comma_not_usable(self):
        # 読点が無い「Aの〜からBの〜へ」型も同様に拒否すること
        text = "警戒から秩序へ。"
        assert _is_usable_bridge_text(text) is False

    def test_backward_reference_bridge_text_not_usable(self):
        # 前記事の内容を要約・振り返る表現を含むbridge_textも拒否すること
        text = "前の記事の結論を踏まえると"
        assert _is_usable_bridge_text(text) is False

    def test_natural_short_bridge_with_kara_not_matching_contrast_pattern_is_usable(self):
        # 「から」を含んでいても「〜へ」で終わる対比構造でなければ
        # 誤って拒否しないこと（過剰検知の回帰確認）
        text = "この流れから、次はテクノロジーの話題です"
        assert _is_usable_bridge_text(text) is True


class TestEnsureTransitionsEpisode362Regression:
    """エピソード362で確認された壊れたtransitionの実例が、修正後の
    _ensure_transitions() では再現しないことを確認する回帰テスト（BEE-676）。"""

    def test_no_particle_duplication_when_topic_ends_with_ni(self):
        # 「個別接種にを見てみましょう」のような助詞重複が生成されないこと
        lines = [
            {"section": "intro", "speaker": "male", "text": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2"},
        ]
        summaries = [
            {"id": 1, "title": "トランプ氏の記事", "summary": ""},
            {"id": 2, "title": "ワクチン記事", "summary": "個別接種に、変更する方針だ"},
        ]
        result = _ensure_transitions(lines, summaries)
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert not any("にを" in t for t in transition_texts), transition_texts
        for t in transition_texts:
            assert _is_broken_transition_text(t) is False, t

    def test_no_mid_word_truncation_for_long_title_without_early_boundary(self):
        # 「事実があっ」のような語中切断が生成されないこと。区切り文字が
        # 25文字以内に無いタイトルは、途中で切らず汎用語へフォールバックする
        lines = [
            {"section": "intro", "speaker": "male", "text": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2"},
        ]
        long_title_no_early_boundary = (
            "イオン系列店舗で発生した避難誘導トラブルに関する詳細報告、一時入館を認めた事実があった"
        )
        summaries = [
            {"id": 1, "title": "記事1タイトル", "summary": ""},
            {"id": 2, "title": long_title_no_early_boundary, "summary": ""},
        ]
        result = _ensure_transitions(lines, summaries)
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert not any("事実があっ" in t for t in transition_texts), transition_texts
        # 区切り文字が見つからないため、不完全な話題名の代わりに汎用語
        # 「次の話題」へフォールバックしていること
        assert any("次の話題" in t for t in transition_texts), transition_texts

    def test_verbose_bridge_text_falls_back_to_normal_template(self):
        # 分析的なメタ注記（bridge_text）が、既知テンプレート形状に一致して
        # いても読み上げ用transitionへそのまま混入しないこと（受入条件）
        lines = [
            {"section": "intro", "speaker": "male", "text": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2"},
        ]
        summaries = [
            {"id": 1, "title": "トランプ氏の記事"},
            {"id": 2, "title": "ワクチン方針"},
        ]
        verbose_bridge = (
            "トランプ氏の極秘移動が示す「安全への過度な警戒」から、"
            "ワクチン義務の変更という「管理された秩序」へ。"
        )
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": verbose_bridge},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert not any(verbose_bridge in t for t in transition_texts), transition_texts
        for t in transition_texts:
            assert _is_broken_transition_text(t) is False, t

    def test_analytical_two_sentence_bridge_text_falls_back(self):
        # 前記事の要約2文がbridge_textとして混在するケースも安全に
        # フォールバックすること
        lines = [
            {"section": "intro", "speaker": "male", "text": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2"},
        ]
        summaries = [
            {"id": 1, "title": "避難計画の記事"},
            {"id": 2, "title": "現場管理の記事"},
        ]
        two_sentence_bridge = (
            "家庭内の混乱が、企業の安全対策という「大規模な現場管理」の失敗へとつながる。"
            "理想の避難計画と現実の混乱。"
        )
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": two_sentence_bridge},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert not any(text_part in t for t in transition_texts for text_part in ("家庭内の混乱", "理想の避難計画")), transition_texts
        for t in transition_texts:
            assert _is_broken_transition_text(t) is False, t

    def test_short_analytical_contrast_bridge_text_falls_back(self):
        # CodeReviewer must指摘(BEE-676): 40文字以下・単文の
        # 「安全への警戒から、秩序の変化へ。」型bridge_textが、修正前は
        # 品質ゲートを通過し「安全への警戒から、秩序の変化へ。 続いては
        # 記事二の最新情報です。」のように前記事の分析と次記事告知が
        # 同一行に混在した状態で生成されていた。修正後はbridgeを使わない
        # 通常テンプレートへフォールバックし、この文言が最終台本に
        # 残らないこと。
        lines = [
            {"section": "intro", "speaker": "male", "text": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "記事1"},
            {"section": "news", "article_id": 2, "speaker": "male", "text": "記事2"},
        ]
        summaries = [
            {"id": 1, "title": "移動記事"},
            {"id": 2, "title": "ワクチン記事"},
        ]
        short_analytical_bridge = "安全への警戒から、秩序の変化へ。"
        assert len(short_analytical_bridge) < 40
        arc = {
            "bridges": [
                {"from_article_id": 1, "to_article_id": 2, "bridge_text": short_analytical_bridge},
            ],
        }
        result = _ensure_transitions(lines, summaries, arc=arc)
        transition_texts = [l["text"] for l in result if l["section"] == "transition"]
        assert not any(short_analytical_bridge in t for t in transition_texts), transition_texts
        assert not any("秩序の変化へ" in t for t in transition_texts), transition_texts
        for t in transition_texts:
            assert _is_broken_transition_text(t) is False, t

        art2_transitions = [
            l for l in result if l["section"] == "transition" and l.get("article_id") == 2
        ]
        assert len(art2_transitions) == 2
        assert art2_transitions[0]["speaker"] != art2_transitions[1]["speaker"]

