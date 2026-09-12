"""レビュー後の音声化前最終検証のテスト。"""

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
         patch.object(radio_pipeline, "synthesize_episode") as synth, \
         patch("shutil.copy"):
        result = radio_pipeline.run_radio_pipeline(
            episode_id,
            episode_date="2099-01-02",
            default_episodes_dir="episodes",
        )

    assert result is None
    final_check.assert_called_once()
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
