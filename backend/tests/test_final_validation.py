"""レビュー後の音声化前最終検証のテスト。"""

import json
from dataclasses import replace
from unittest.mock import patch


def _line(section, text, speaker="male", article_id=1):
    return {
        "section": section,
        "text": text,
        "speaker": speaker,
        "article_id": None if section in {"intro", "outro"} else article_id,
    }


def _valid_lines():
    return [
        _line("intro", "「ニュースのとなり」の時間です。", article_id=None),
        _line("news", "認証機能が発表されました。"),
        _line("transition", "続いて別の話題です。", article_id=2),
        _line("discussion", "この仕組みの特徴を整理します。"),
        _line("discussion", "利用条件を確認できます。", speaker="female"),
        _line("discussion", "要約には登録端末で本人確認とあります。"),
        _line("discussion", "生活への影響を考えたいですね。", speaker="female"),
        _line("outro", "今日は認証機能について振り返りました。", article_id=None),
        _line("outro", "みなさんはどう感じましたか？", speaker="female", article_id=None),
        _line("outro", "それではまた明日、お会いしましょう。", article_id=None),
    ]


def test_final_validation_passes_without_warnings():
    from app.batch import final_validation

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(_valid_lines())

    assert result["status"] == "passed"
    assert result["can_synthesize"] is True
    assert result["critical_issues"] == []


def test_custom_headline_corner_layout_is_validated_in_profile_order():
    from app.batch.final_validation import validate_final_script
    from app.programs.profiles import ProgramSegment, RADIO_TWO_PERSON

    profile = replace(
        RADIO_TWO_PERSON,
        id="radio_with_features",
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male", "female")),
            ProgramSegment("discussion", "discussion", 1, 1, 1, ("male", "female")),
            ProgramSegment("news", "news", 2, 1, 1, ("male", "female")),
            ProgramSegment("headline", "headline", 3, 1, 1, ("male", "female")),
            ProgramSegment("outro", "outro", 4, 2, 2, ("male", "female")),
            ProgramSegment("corner", "corner", 5, 1, 1, ("male", "female")),
        ),
    )
    sections_and_ids = [
        ("intro", "intro"),
        ("discussion", "discussion"),
        ("news", "news"),
        ("headline", "headline"),
        ("outro", "outro"),
        ("outro", "outro"),
        ("corner", "corner"),
    ]
    lines = [
        {
            "speaker": "male",
            "section": section,
            "segment": segment_id,
            "text": text,
            "article_id": None if section in {"intro", "outro"} else 1,
        }
        for (section, segment_id), text in zip(
            sections_and_ids,
            [
                "「ニュースのとなり」の時間です。本日のニュースをお伝えします。",
                "記事の背景を整理します。",
                "記事の内容です。",
                "見出しを紹介します。",
                "今日は何が気になりましたか？",
                "それではまた次回お会いしましょう。",
                "今日のコーナーです。",
            ],
        )
    ]

    result = validate_final_script(lines, program_profile=profile)

    codes = {finding["code"] for finding in result["critical_issues"]}
    assert "DISCUSSION_LAYOUT" not in codes
    assert "DISCUSSION_POSITION" not in codes
    assert "DISCUSSION_LENGTH" not in codes
    assert "OUTRO_POSITION" not in codes
    assert "SEGMENT_ORDER" not in codes
    assert result["can_synthesize"] is True
    assert [line["section"] for line in result["lines"]] == [section for section, _ in sections_and_ids]


def test_final_validation_clears_stale_transition_critical_after_script_was_repaired(tmp_path):
    """ep543: review snapshotで壊れていたtransitionが修正済みなら最終判定を通す。"""
    from app.batch.final_validation import validate_final_script_file

    script_path = tmp_path / "script.json"
    script_path.write_text(
        json.dumps({"lines": _valid_lines()}, ensure_ascii=False),
        encoding="utf-8",
    )
    prior_review_result = {
        "transition_integrity_issues": [
            "[TRANSITION_MIXED] transition行 2 に前の記事の締め文と次の記事の告知が混在"
        ]
    }

    with patch("app.batch.final_validation.lint_script", return_value=[]):
        result = validate_final_script_file(
            str(script_path),
            prior_review_result=prior_review_result,
        )

    assert result["status"] == "passed"
    assert result["can_synthesize"] is True
    assert not any(item["code"] == "TRANSITION_INTEGRITY" for item in result["critical_issues"])


def test_final_validation_keeps_broken_transition_as_critical():
    """BEE-661/BEE-355: 最終scriptにも異常transitionが残る場合は人間確認を止めない。"""
    from app.batch import final_validation

    lines = [
        _line("intro", "「ニュースのとなり」の時間です。", article_id=None),
        _line("news", "海外邦人についての記事です。", article_id=1),
        _line(
            "transition",
            "制度の不備という見えない制約から、人身の自由を奪う見えない組織への恐怖へ。"
            "海外邦人の窮状は社会構造の歪みを象徴する それでは、"
            "カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。",
            speaker="female",
            article_id=2,
        ),
        _line("news", "行方不明事案についての記事です。", article_id=2),
    ]

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(lines, style="solo")

    assert result["status"] == "human_review"
    assert result["can_synthesize"] is False
    assert any(item["code"] == "TRANSITION_INTEGRITY" for item in result["critical_issues"])


def test_final_validation_preserves_known_transition_templates():
    """BEE-664: 既知の通常・Bridgeテンプレートを誤検知・書き換えしない。"""
    from app.batch import final_validation
    from app.batch.generate_script import _BRIDGE_TRANSITION_PHRASES, _TRANSITION_PHRASES

    templates = [
        phrase.format(topic="経済") for phrase in _TRANSITION_PHRASES
    ] + [
        phrase.format(bridge="気候変動の影響は経済にも及んでいます", topic="テクノロジー")
        for phrase in _BRIDGE_TRANSITION_PHRASES
    ]
    assert len(_TRANSITION_PHRASES) == 31
    assert len(_BRIDGE_TRANSITION_PHRASES) == 6

    with patch.object(final_validation, "lint_script", return_value=[]):
        for text in templates:
            lines = _valid_lines()
            lines[2]["text"] = text
            result = final_validation.validate_final_script(lines)

            assert result["can_synthesize"] is True, text
            assert not any(
                item["code"] == "TRANSITION_INTEGRITY"
                for item in result["critical_issues"]
            ), text
            assert result["lines"][2]["text"] == text


def test_minor_lint_warning_does_not_stop_synthesis():
    from app.batch import final_validation

    with patch.object(final_validation, "lint_script", return_value=["[WARN][TRANS_VARIATION] 語尾の偏り"]):
        result = final_validation.validate_final_script(_valid_lines())

    assert result["status"] == "warning"
    assert result["can_synthesize"] is True
    assert result["warnings"][0]["code"] == "TRANS_VARIATION"


def test_unanswered_question_requires_human_review():
    from app.batch import final_validation

    lines = _valid_lines()
    lines[1]["text"] = "料金はいくらですか？"
    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(lines)

    assert result["status"] == "human_review"
    assert result["can_synthesize"] is False
    assert any(item["code"] == "DIRECT_ANSWER_MISSING" for item in result["critical_issues"])


def test_question_after_farewell_is_removed_from_outro_only():
    from app.batch import final_validation

    lines = _valid_lines()
    lines.append(_line("outro", "最後に、みなさんはどう感じましたか？", article_id=None))
    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(lines)

    assert result["can_synthesize"] is True
    assert len(result["lines"]) == len(lines) - 1
    assert result["lines"][-1]["text"] == "それではまた明日、お会いしましょう。"
    assert result["repairs"][0]["code"] == "OUTRO_QUESTION_REINSERTED"


def test_inappropriate_sensitive_reaction_requires_human_review():
    from app.batch import final_validation

    lines = _valid_lines()
    lines[2]["text"] = "楽しみな話題です。"
    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(
            lines,
            summaries=[{"id": 2, "title": "大雨の被害", "summary": "避難情報が出ました。"}],
        )

    assert result["status"] == "human_review"
    assert any(item["code"] == "INAPPROPRIATE_REACTION" for item in result["critical_issues"])


def test_hold_for_human_review_persists_status_phase_and_reason():
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode("2099-01-01", status="generating")
    service.hold_for_human_review(episode_id, "重大違反: 質問への回答がありません")

    episode = service.get_episode(episode_id)
    assert episode["status"] == "failed"
    assert episode["phase"] == "human_review"
    assert "質問への回答がありません" in episode["generation_message"]


def test_final_validation_gate_keeps_revised_contract():
    from app.batch.final_validation import should_run_final_validation

    review_result = {
        "revised": False,
        "review_count": 5,
        "dialogue_balance_issues": [],
        "question_response_issues": [],
        "transition_integrity_issues": [],
    }

    assert should_run_final_validation("missing-script.json", review_result) is False

    review_result["revised"] = True
    assert should_run_final_validation("missing-script.json", review_result) is True


def test_final_validation_gate_runs_after_review_rejects_transition():
    from app.batch.final_validation import should_run_final_validation

    review_result = {
        "revised": False,
        "review_count": 5,
        "transition_integrity_issues": ["[TRANSITION_MIXED] transitionが壊れています"],
    }

    assert should_run_final_validation("missing-script.json", review_result) is True


def test_final_validation_gate_runs_for_recorded_discussion_layout_issue(tmp_path):
    from app.batch.final_validation import should_run_final_validation

    script_path = tmp_path / "script.json"
    script_path.write_text(
        json.dumps({"discussion_layout_issues": [{"code": "DISCUSSION_ARTICLE_POSITION"}]}),
        encoding="utf-8",
    )

    assert should_run_final_validation(str(script_path), {"revised": False, "review_count": 5}) is True


def test_radio_pipeline_stops_before_tts_when_final_validation_is_unresolved():
    from app.batch import radio_pipeline
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode("2099-01-02", status="generating")
    review_result = {
        "revised": True,
        "review_count": 5,
        "dialogue_balance_issues": [],
        "question_response_issues": [],
        "transition_integrity_issues": [],
    }
    final_result = {
        "can_synthesize": False,
        "status": "human_review",
        "critical_issues": [{"code": "DIRECT_ANSWER_MISSING", "message": "回答なし"}],
        "warnings": [],
        "repairs": [],
        "lines": [],
    }

    with patch.object(radio_pipeline, "import_articles_by_source", return_value=(1, 0)), \
         patch.object(radio_pipeline, "summarize_articles", return_value=1), \
         patch.object(radio_pipeline, "generate_script", return_value=1), \
         patch.object(radio_pipeline, "override_script_title"), \
         patch.object(radio_pipeline, "review_script", return_value=review_result), \
         patch.object(radio_pipeline, "validate_final_script_file", return_value=final_result) as final_check, \
         patch.object(radio_pipeline, "notify_failure") as notify_failure, \
         patch.object(radio_pipeline, "synthesize_episode") as synth, \
         patch("shutil.copy"):
        result = radio_pipeline.run_radio_pipeline(
            episode_id,
            episode_date="2099-01-02",
            default_episodes_dir="episodes",
        )

    assert result is None
    final_check.assert_called_once()
    notify_failure.assert_called_once()
    assert notify_failure.call_args.kwargs["episode_id"] == episode_id
    assert notify_failure.call_args.kwargs["phase"] == "human_review"
    synth.assert_not_called()
    episode = service.get_episode(episode_id)
    assert episode["status"] == "failed"
    assert episode["phase"] == "human_review"
    assert "回答なし" in episode["generation_message"]


def test_commentary_shape_does_not_require_radio_outro_contract():
    from app.batch import final_validation

    lines = [
        _line("intro", "今日は記事を解説します。"),
        _line("news", "発表された内容を数字とともに整理します。"),
        _line("outro", "今回は発表の背景を振り返りました。"),
    ]

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(lines, commentary=True, style="solo")

    assert result["status"] == "passed"
    assert result["can_synthesize"] is True


def test_final_validation_reorders_discussion_after_all_news():
    from app.batch import final_validation

    lines = [
        _line("intro", "「ニュースのとなり」の時間です。", article_id=None),
        _line("news", "記事1です。", article_id=1),
        _line("transition", "記事3へ移ります。", article_id=3),
        _line("news", "記事3です。", article_id=3),
        _line("transition", "記事2へ移ります。", article_id=2),
        _line("news", "記事2です。", article_id=2),
        _line("transition", "記事2を深掘りします。", article_id=2),
        _line("discussion", "記事2のポイントです。", article_id=2),
        _line("discussion", "利用者への影響を見ます。", speaker="female", article_id=2),
        _line("discussion", "背景も確認できます。", article_id=2),
        _line("discussion", "重要な動きですね。", speaker="female", article_id=2),
        _line("transition", "記事4へ移ります。", article_id=4),
        _line("news", "記事4です。", article_id=4),
        _line("outro", "今日は記事2を振り返りました。", article_id=None),
        _line("outro", "みなさんはどう感じましたか？", speaker="female", article_id=None),
        _line("outro", "それではまた明日、お会いしましょう。", article_id=None),
    ]

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(
            lines,
            expected_discussion_article_id=2,
        )

    assert result["can_synthesize"] is True
    news_ids = [line["article_id"] for line in result["lines"] if line["section"] == "news"]
    discussion_indices = [i for i, line in enumerate(result["lines"]) if line["section"] == "discussion"]
    assert news_ids[-1] == 2
    assert min(discussion_indices) > max(i for i, line in enumerate(result["lines"]) if line["section"] == "news")
    assert result["lines"][-1]["section"] == "outro"
    assert any(item["code"] == "DISCUSSION_REORDERED" for item in result["repairs"])


def test_final_validation_reorders_fifty_eight_article_case():
    from app.batch import final_validation

    target_id = 58147
    lines = [_line("intro", "「ニュースのとなり」の時間です。", article_id=None)]
    for article_id in range(1, 59):
        if article_id > 1:
            lines.append(_line("transition", f"記事{article_id}へ移ります。", article_id=article_id))
        lines.append(_line("news", f"記事{article_id}です。", article_id=target_id if article_id == 6 else article_id))
        if article_id == 6:
            lines.extend([
                _line("transition", "記事58147を詳しく見ていきましょう。", article_id=target_id),
                _line("discussion", "記事58147の背景を確認します。", article_id=target_id),
                _line("discussion", "影響を整理できます。", speaker="female", article_id=target_id),
                _line("discussion", "今後の動きも注目です。", article_id=target_id),
                _line("discussion", "大切な論点ですね。", speaker="female", article_id=target_id),
            ])
    lines.extend([
        _line("outro", "今日はニュースを振り返りました。", article_id=None),
        _line("outro", "みなさんはどう感じましたか？", speaker="female", article_id=None),
        _line("outro", "それではまた明日、お会いしましょう。", article_id=None),
    ])

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(
            lines,
            expected_discussion_article_id=target_id,
        )

    assert result["can_synthesize"] is True
    assert [line["article_id"] for line in result["lines"] if line["section"] == "news"][-1] == target_id
    discussion_indices = [i for i, line in enumerate(result["lines"]) if line["section"] == "discussion"]
    assert min(discussion_indices) > max(i for i, line in enumerate(result["lines"]) if line["section"] == "news")
    assert result["lines"][-1]["section"] == "outro"


def test_final_validation_blocks_when_discussion_target_news_is_missing():
    from app.batch import final_validation

    lines = _valid_lines()
    for line in lines:
        if line["section"] == "discussion":
            line["article_id"] = 999

    with patch.object(final_validation, "lint_script", return_value=[]):
        result = final_validation.validate_final_script(
            lines,
            expected_discussion_article_id=999,
        )

    assert result["can_synthesize"] is False
    assert any(item["code"] == "DISCUSSION_ARTICLE_POSITION" for item in result["critical_issues"])


def test_final_validation_file_preserves_arc_discussion_target(tmp_path):
    from app.batch.final_validation import validate_final_script_file

    script_path = tmp_path / "script.json"
    script_path.write_text(
        json.dumps({
            "discussion_article_id": 2,
            "lines": [
                _line("intro", "「ニュースのとなり」の時間です。", article_id=None),
                _line("news", "記事1です。", article_id=1),
                _line("discussion", "記事1の討論です。", article_id=1),
                _line("discussion", "影響を見ます。", speaker="female", article_id=1),
                _line("discussion", "背景を確認します。", article_id=1),
                _line("discussion", "大切な論点です。", speaker="female", article_id=1),
                _line("outro", "今日は記事を振り返りました。", article_id=None),
                _line("outro", "みなさんはどう感じましたか？", speaker="female", article_id=None),
                _line("outro", "それではまた明日、お会いしましょう。", article_id=None),
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    with patch("app.batch.final_validation.lint_script", return_value=[]):
        result = validate_final_script_file(str(script_path))

    assert result["can_synthesize"] is False
    assert any(item["code"] == "DISCUSSION_ARTICLE_DRIFT" for item in result["critical_issues"])


def test_same_article_id_in_multiple_news_blocks_is_recorded_without_rewrite():
    from app.batch.final_validation import article_recurrence_issues

    lines = [
        _line("news", "中部電力が発表しました。", article_id=502),
        _line("transition", "続いて別の話題です。", article_id=503),
        _line("news", "別の記事を紹介します。", article_id=503),
        _line("transition", "話題を戻します。", article_id=502),
        _line("news", "中部電力の追加情報です。", article_id=502),
    ]

    findings = article_recurrence_issues(lines, [])

    assert len(findings) == 1
    assert findings[0]["code"] == "ARTICLE_REUSED_IN_NEWS_BLOCKS"
    assert findings[0]["article_ids"] == [502]
    assert findings[0]["review_status"] == "pending_human_review"
    assert findings[0]["auto_action"] == "none"
    assert findings[0]["line_indices"] == [0, 4]


def test_different_article_ids_with_shared_subject_are_recorded_with_evidence():
    from app.batch.final_validation import article_recurrence_issues

    lines = [
        _line("news", "中部電力の原発再稼働を伝えます。", article_id=10),
        _line("transition", "次の話題です。", article_id=11),
        _line("news", "中部電力の料金改定を伝えます。", article_id=11),
    ]
    summaries = [
        {"id": 10, "title": "中部電力、原発再稼働を申請"},
        {"id": 11, "title": "中部電力、料金改定を発表"},
    ]

    findings = article_recurrence_issues(lines, summaries)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["code"] == "RELATED_TOPIC_REAPPEARANCE"
    assert finding["article_ids"] == [10, 11]
    assert finding["evidence"]["detection_method"] == "shared_title_anchor"
    assert "中部電力" in finding["evidence"]["shared_title_anchors"]
    assert finding["review_status"] == "pending_human_review"
    assert finding["auto_action"] == "none"


def test_fifty_article_case_is_inspected_without_collapsing_distinct_articles():
    from app.batch.final_validation import article_recurrence_issues

    lines = []
    summaries = []
    for article_id in range(1, 51):
        lines.append(_line("news", f"記事{article_id}の内容です。", article_id=article_id))
        summaries.append({"id": article_id, "title": f"Entity{article_id} announces"})

    findings = article_recurrence_issues(lines, summaries)

    assert findings == []
