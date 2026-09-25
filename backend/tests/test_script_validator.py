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
    assert all({"code", "message", "line_indices", "severity"} <= finding.keys() for finding in findings)


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
