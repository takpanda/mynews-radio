from dataclasses import replace

import pytest

from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
    COMMENTARY_TWO_PERSON,
    DEFAULT_PROFILES,
    RADIO_TWO_PERSON,
    ProgramCastMember,
    ProgramSegment,
    ProfileValidationError,
    get_default_profile,
    validate_program_profile,
)


@pytest.mark.parametrize(
    ("kwargs", "expected_id", "expected_keys", "expected_order"),
    [
        (
            {"kind": "radio"},
            "radio_news_neighbor",
            ("male", "female"),
            ("intro", "transition", "news", "discussion", "outro"),
        ),
        (
            {"kind": "radio", "program_name": "テックニュース", "news_source": "yahoo_news"},
            "radio_tech_news",
            ("male", "female"),
            ("intro", "transition", "news", "discussion", "outro"),
        ),
        (
            {"kind": "radio", "news_source": "hatena_bookmark"},
            "radio_tech_news",
            ("male", "female"),
            ("intro", "transition", "news", "discussion", "outro"),
        ),
        (
            {"kind": "radio", "program_name": "ニュースのとなり", "news_source": "hatena_bookmark"},
            "radio_news_neighbor",
            ("male", "female"),
            ("intro", "transition", "news", "discussion", "outro"),
        ),
        (
            {"kind": "commentary", "style": "solo", "mc_gender": "female"},
            "commentary_solo",
            ("female",),
            ("intro", "news", "outro"),
        ),
        (
            {"kind": "commentary", "style": "dialogue"},
            "commentary_dialogue",
            ("male", "female"),
            ("intro", "news", "outro"),
        ),
    ],
)
def test_current_generation_arguments_resolve_profile(kwargs, expected_id, expected_keys, expected_order):
    profile = get_default_profile(**kwargs)

    assert profile.id == expected_id
    assert tuple(member.key for member in profile.cast) == expected_keys
    assert tuple(segment.kind for segment in profile.segments) == expected_order
    validate_program_profile(profile)


def test_default_profiles_cover_three_existing_program_modes():
    assert tuple(profile.id for profile in DEFAULT_PROFILES) == (
        RADIO_TWO_PERSON.id,
        COMMENTARY_ONE_PERSON.id,
        COMMENTARY_TWO_PERSON.id,
    )


def test_commentary_line_ranges_cover_current_prompt_conditions():
    solo = get_default_profile(kind="commentary", style="solo")
    dialogue = get_default_profile(kind="commentary", style="dialogue")

    def bounds(profile):
        return {
            segment.kind: (segment.min_lines, segment.max_lines)
            for segment in profile.segments
        }

    assert bounds(solo) == {"intro": (1, 2), "news": (3, 12), "outro": (1, 2)}
    assert bounds(dialogue) == {"intro": (1, 3), "news": (3, 12), "outro": (1, 2)}
    assert bounds(dialogue)["outro"][0] == 1


def test_explicit_radio_program_name_takes_precedence_over_news_source():
    profile = get_default_profile(
        kind="radio",
        program_name="ニュースのとなり",
        news_source="hatena_bookmark",
    )

    assert profile.id == "radio_news_neighbor"


@pytest.mark.parametrize(
    "profile",
    [
        replace(RADIO_TWO_PERSON, kind="podcast"),
        replace(RADIO_TWO_PERSON, cast=RADIO_TWO_PERSON.cast + (ProgramCastMember("male", "重複"),)),
        replace(
            RADIO_TWO_PERSON,
            segments=RADIO_TWO_PERSON.segments
            + (ProgramSegment("intro", "intro", 5, 1, 1),),
        ),
        replace(
            RADIO_TWO_PERSON,
            segments=RADIO_TWO_PERSON.segments
            + (ProgramSegment("news_followup", "news", 5, 1, 1),),
        ),
        replace(
            RADIO_TWO_PERSON,
            segments=(replace(RADIO_TWO_PERSON.segments[0], kind="unknown"),)
            + RADIO_TWO_PERSON.segments[1:],
        ),
        replace(
            RADIO_TWO_PERSON,
            segments=(replace(RADIO_TWO_PERSON.segments[0], order=1),)
            + RADIO_TWO_PERSON.segments[1:],
        ),
        replace(
            RADIO_TWO_PERSON,
            segments=(replace(RADIO_TWO_PERSON.segments[0], speaker_keys=("unknown",)),)
            + RADIO_TWO_PERSON.segments[1:],
        ),
        replace(
            RADIO_TWO_PERSON,
            segments=(replace(RADIO_TWO_PERSON.segments[0], min_lines=6),)
            + RADIO_TWO_PERSON.segments[1:],
        ),
    ],
)
def test_invalid_profile_is_rejected(profile):
    with pytest.raises(ProfileValidationError):
        validate_program_profile(profile)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "video"}, "unsupported program kind"),
        ({"kind": "commentary", "style": "monologue"}, "unsupported commentary style"),
        ({"kind": "commentary", "style": "solo", "mc_gender": "other"}, "unsupported commentary mc_gender"),
    ],
)
def test_unknown_current_selector_values_fail(kwargs, message):
    with pytest.raises(ValueError, match=message):
        get_default_profile(**kwargs)
