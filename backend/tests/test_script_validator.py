from dataclasses import replace

from app.batch.generate_script import lint_script
from app.batch.script_validator import ScriptValidator
from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
    COMMENTARY_TWO_PERSON,
    ProgramCastMember,
    ProgramSegment,
    RADIO_TWO_PERSON,
    get_profile_by_id,
)


def test_profile_lint_keeps_legacy_lint_messages_and_adds_unknown_speaker_check():
    validator = ScriptValidator(RADIO_TWO_PERSON)
    lines = [
        {"speaker": "guest", "section": "intro", "text": "導入です。"},
    ]

    structured = validator.validate(lines)
    assert any(issue["code"] == "UNKNOWN_SPEAKER" for issue in structured)
    assert all({"code", "message", "line_indices", "severity"} <= issue.keys() for issue in structured)
    assert any("UNKNOWN_SPEAKER" not in message for message in lint_script(lines, program_profile=RADIO_TWO_PERSON))


def test_validator_detects_segment_order_and_line_count_bounds():
    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("news", "news", 1, 2, 2, ("male",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("male",)),
        ),
    )
    lines = [
        {"speaker": "male", "section": "news", "segment": "news", "text": "本文です。"},
        {"speaker": "male", "section": "intro", "segment": "intro", "text": "導入です。"},
        {"speaker": "male", "section": "outro", "segment": "outro", "text": "結びです。"},
    ]

    findings = ScriptValidator(profile).validate_structure(lines)
    assert [finding["code"] for finding in findings] == ["SEGMENT_ORDER", "SEGMENT_LINE_COUNT"]
    assert findings[0]["line_indices"] == [0, 1, 2]


def test_validator_detects_segment_line_count_overflow():
    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("news", "news", 1, 1, 1, ("male",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("male",)),
        ),
    )
    lines = [
        {"speaker": "male", "section": "intro", "segment": "intro", "text": "導入です。"},
        {"speaker": "male", "section": "news", "segment": "news", "text": "説明です。"},
        {"speaker": "male", "section": "news", "segment": "news", "text": "補足です。"},
        {"speaker": "male", "section": "outro", "segment": "outro", "text": "結びです。"},
    ]

    findings = ScriptValidator(profile).validate_structure(lines)
    overflow = next(finding for finding in findings if finding["code"] == "SEGMENT_LINE_COUNT")
    assert "2行" in overflow["message"]
    assert overflow["line_indices"] == [1, 2]


def test_validator_uses_ids_for_repeated_kinds_and_added_section_kinds():
    from app.programs.profiles import validate_program_profile

    profile = replace(
        COMMENTARY_TWO_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("headline_open", "headline", 1, 1, 1, ("male",)),
            ProgramSegment("news", "news", 2, 1, 1, ("male", "female")),
            ProgramSegment("headline_wrap", "headline", 3, 1, 1, ("female",)),
            ProgramSegment("daily_corner", "corner", 4, 1, 1, ("male",)),
            ProgramSegment("outro", "outro", 5, 1, 1, ("female",)),
        ),
    )
    validate_program_profile(profile)
    lines = [
        {"speaker": "male", "section": "intro", "segment": "intro"},
        {"speaker": "male", "section": "headline", "segment": "headline_open"},
        {"speaker": "male", "section": "news", "segment": "news"},
        {"speaker": "female", "section": "headline", "segment": "headline_wrap"},
        {"speaker": "male", "section": "corner", "segment": "daily_corner"},
        {"speaker": "female", "section": "outro", "segment": "outro"},
    ]

    assert ScriptValidator(profile).validate_structure(lines) == []


def test_validator_reports_ambiguous_missing_and_unknown_segment_ids():
    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("headline_open", "headline", 0, 1, 1, ("male",)),
            ProgramSegment("headline_wrap", "headline", 1, 1, 1, ("male",)),
        ),
    )

    findings = ScriptValidator(profile).validate_structure([
        {"speaker": "male", "section": "headline", "segment": "unregistered"},
        {"speaker": "male", "section": "headline"},
    ])

    codes = [finding["code"] for finding in findings]
    assert "UNKNOWN_SEGMENT" in codes
    missing = [finding for finding in findings if finding["code"] == "SEGMENT_MISSING"]
    assert len(missing) == 1
    assert missing[0]["line_indices"] == [1]
    assert all(finding["line_indices"] != [0] for finding in findings if finding["code"] == "SEGMENT_LINE_COUNT")


def test_validator_checks_order_line_counts_and_speakers_per_segment_id():
    profile = replace(
        COMMENTARY_TWO_PERSON,
        segments=(
            ProgramSegment("headline_open", "headline", 0, 1, 1, ("male",)),
            ProgramSegment("headline_wrap", "headline", 1, 2, 2, ("female",)),
        ),
    )
    findings = ScriptValidator(profile).validate_structure([
        {"speaker": "male", "section": "headline", "segment": "headline_wrap"},
        {"speaker": "male", "section": "headline", "segment": "headline_open"},
    ])

    codes = [finding["code"] for finding in findings]
    assert "SEGMENT_SPEAKER" in codes
    assert "SEGMENT_ORDER" in codes
    count_findings = [finding for finding in findings if finding["code"] == "SEGMENT_LINE_COUNT"]
    assert len(count_findings) == 1
    assert count_findings[0]["line_indices"] == [0]
    assert "headline_wrap" in count_findings[0]["message"]


def test_missing_segment_id_is_reported_and_section_fallback_keeps_structure_checks():
    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("news", "news", 1, 2, 2, ("male",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("male",)),
        ),
    )
    lines = [
        {"speaker": "male", "section": "intro", "segment": "intro", "text": "導入です。"},
        {"speaker": "male", "section": "outro", "segment": "outro", "text": "結びです。"},
        {"speaker": "male", "section": "news", "text": "本文です。"},
    ]

    findings = ScriptValidator(profile).validate_structure(lines)
    codes = [finding["code"] for finding in findings]
    assert "SEGMENT_MISSING" in codes
    assert "SEGMENT_ORDER" in codes
    assert "SEGMENT_LINE_COUNT" in codes
    missing = next(finding for finding in findings if finding["code"] == "SEGMENT_MISSING")
    assert missing["line_indices"] == [2]


def test_one_person_profile_checks_solo_style_and_skips_dialogue_rules():
    validator = ScriptValidator(COMMENTARY_ONE_PERSON)
    lines = [
        {"speaker": "male", "section": "news", "text": "どうしてでしょうか？"},
        {"speaker": "male", "section": "news", "text": "そうですね。"},
    ]

    findings = validator.validate_structure(lines)
    assert [finding["code"] for finding in findings].count("SOLO_DIALOGUE_STYLE") == 2
    assert validator.dialogue_issues(lines) == []


def test_multi_person_profile_runs_dialogue_balance_for_profile_speakers():
    profile = replace(
        COMMENTARY_TWO_PERSON,
        cast=(ProgramCastMember("expert", "佐藤", "解説者"), ProgramCastMember("host", "鈴木", "聞き手")),
        segments=tuple(
            replace(segment, speaker_keys=("expert", "host"))
            for segment in COMMENTARY_TWO_PERSON.segments
        ),
    )
    lines = [
        {"speaker": "host", "section": "news", "text": "なぜでしょうか？"},
        {"speaker": "expert", "section": "news", "text": "理由を説明します。"},
    ]

    messages = ScriptValidator(profile).dialogue_issues(lines)
    assert any("鈴木" in message for message in messages)
    assert any("佐藤" in message for message in messages)


def test_structured_validate_includes_dialogue_and_question_response_findings():
    profile = replace(
        COMMENTARY_TWO_PERSON,
        cast=(ProgramCastMember("expert", "佐藤", "解説者"), ProgramCastMember("host", "鈴木", "聞き手")),
        segments=tuple(
            replace(segment, speaker_keys=("expert", "host"))
            for segment in COMMENTARY_TWO_PERSON.segments
        ),
    )
    lines = [
        {"speaker": "host", "section": "news", "text": "なぜでしょうか？"},
        {"speaker": "expert", "section": "news", "text": "理由を説明します。"},
    ]

    findings = ScriptValidator(profile).validate(lines)
    codes = [finding["code"] for finding in findings]
    assert "HOST_QUESTION_ONLY" in codes
    assert "QA_RELAY" in codes
    severities = {finding["code"]: finding["severity"] for finding in findings}
    assert severities["HOST_QUESTION_ONLY"] == "warning"
    assert severities["QA_RELAY"] == "warning"
    assert all({"code", "message", "line_indices", "severity"} <= finding.keys() for finding in findings)


def test_structured_validate_marks_dialogue_findings_as_warnings_and_missing_answer_as_error():
    validator = ScriptValidator(COMMENTARY_TWO_PERSON)
    lines = [
        {"speaker": "female", "section": "news", "text": "なぜでしょうか？"},
    ]

    findings = validator.validate(lines)
    severities = {finding["code"]: finding["severity"] for finding in findings}
    assert severities["FEMALE_QUESTION_ONLY"] == "warning"
    assert severities["DIRECT_ANSWER_MISSING"] == "error"


def test_reviewed_script_restores_profile_segment_ids_for_structure_validation():
    from app.batch.review_script import _build_revised_script

    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("news", "news", 1, 1, 1, ("male",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("male",)),
        ),
    )
    source = {
        "program_profile_id": profile.id,
        "date": "2026-09-26",
        "title": "元台本",
        "subtitle": "",
        "style": "solo",
        "mc_gender": "male",
    }
    response = {
        "lines": [
            {"section": "intro", "text": "導入です。"},
            {"section": "news", "text": "記事を説明します。"},
            {"section": "outro", "text": "解説を終わります。"},
        ]
    }

    revised = _build_revised_script(source, response, program_profile=profile)

    assert [line["segment"] for line in revised["lines"]] == ["intro", "news", "outro"]
    findings = ScriptValidator(profile).validate_structure(revised["lines"])
    assert not any(finding["code"].startswith("SEGMENT_") for finding in findings)


def test_reviewed_script_preserves_and_reports_section_missing_from_profile():
    from app.batch.review_script import _build_revised_script

    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("male",)),
            ProgramSegment("news", "news", 1, 1, 1, ("male",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("male",)),
        ),
    )
    source = {
        "program_profile_id": profile.id,
        "style": "solo",
        "mc_gender": "male",
    }
    response = {"lines": [{"section": "discussion", "text": "対話形式の行です。"}]}

    revised = _build_revised_script(source, response, program_profile=profile)

    assert revised["lines"][0]["section"] == "discussion"
    assert "segment" not in revised["lines"][0]
    findings = ScriptValidator(profile).validate_structure(revised["lines"])
    unknown = next(finding for finding in findings if finding["code"] == "UNKNOWN_SECTION")
    assert unknown["line_indices"] == [0]


def test_review_postprocessing_preserves_explicit_ids_mismatches_and_ambiguous_rows():
    from app.batch.review_script import _build_revised_script

    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("headline_open", "headline", 0, 1, 1, ("male",)),
            ProgramSegment("headline_wrap", "headline", 1, 1, 1, ("male",)),
            ProgramSegment("daily_corner", "corner", 2, 1, 1, ("male",)),
        ),
    )
    revised = _build_revised_script(
        {"program_profile_id": profile.id},
        {"lines": [
            {"segment": "headline_wrap", "text": "締めの見出しです。"},
            {"section": "headline", "text": "識別できない見出しです。"},
            {"section": "headline", "segment": "daily_corner", "text": "IDと種別が不一致です。"},
        ]},
        program_profile=profile,
    )

    assert revised["lines"][0]["section"] == "headline"
    assert revised["lines"][0]["segment"] == "headline_wrap"
    assert "segment" not in revised["lines"][1]
    assert revised["lines"][2]["section"] == "headline"
    assert revised["lines"][2]["segment"] == "daily_corner"
    findings = ScriptValidator(profile).validate_structure(revised["lines"])
    assert any(finding["code"] == "SEGMENT_MISSING" for finding in findings)
    mismatch = next(finding for finding in findings if finding["code"] == "SEGMENT_SECTION_MISMATCH")
    assert mismatch["line_indices"] == [2]
    from app.batch.final_validation import validate_final_script

    final_result = validate_final_script(
        revised["lines"],
        program_profile=profile,
        commentary=True,
        style="solo",
    )
    assert any(
        finding["code"] == "SEGMENT_SECTION_MISMATCH"
        for finding in final_result["critical_issues"]
    )


def test_legacy_messages_extract_single_list_range_and_joined_line_indexes():
    parse = ScriptValidator.from_legacy_message

    assert parse("[X] transition行 2 と 5 が不正です") ["line_indices"] == [2, 5]
    assert parse("[X] transition行 [1, 2] が不正です") ["line_indices"] == [1, 2]
    assert parse("[X] news行 1〜3 が不正です") ["line_indices"] == [1, 2, 3]


def test_parameterized_registered_profile_resolves_its_configured_speaker():
    profile = get_profile_by_id("commentary_solo", style="solo", mc_gender="female")

    assert profile is not None
    assert profile.speaker_keys == frozenset({"female"})


def test_final_validation_uses_profile_speaker_keys():
    from app.batch.final_validation import validate_final_script

    lines = [
        {"speaker": "guest", "section": "intro", "text": "導入を説明します。"},
        {"speaker": "male", "section": "news", "text": "記事の概要です。"},
        {"speaker": "male", "section": "news", "text": "背景を説明します。"},
        {"speaker": "male", "section": "news", "text": "影響を整理します。"},
        {"speaker": "male", "section": "outro", "text": "解説を終わります。"},
    ]

    result = validate_final_script(lines, commentary=True, style="solo", program_profile=COMMENTARY_ONE_PERSON)
    grammar_issue = next(issue for issue in result["critical_issues"] if issue["code"] == "GRAMMAR_BREAKDOWN")
    assert grammar_issue["line_indices"] == [0]
