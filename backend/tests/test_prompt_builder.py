import json
from dataclasses import replace
import pytest

from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
    RADIO_TWO_PERSON,
    ProgramCastMember,
)
from app.programs.prompt_builder import PromptBuilder


def test_one_person_profile_gets_solo_rules_and_single_line_transitions():
    profile = replace(
        RADIO_TWO_PERSON,
        id="radio_solo",
        cast=(ProgramCastMember("host", "司会", "進行"),),
        segments=tuple(
            replace(segment, speaker_keys=("host",))
            for segment in RADIO_TWO_PERSON.segments
        ),
    )
    builder = PromptBuilder(profile)

    assert "一人語り" in builder.cast_section
    assert "記事間のtransitionは、各記事の間に独立した1行" in builder.structure_section


def test_multi_person_profile_gets_role_guidance_and_dialogue_rules():
    builder = PromptBuilder(RADIO_TWO_PERSON)

    assert "田村" in builder.cast_section
    assert "掛け合い" in builder.structure_section


def test_example_uses_a_defined_segment_and_its_section_kind():
    builder = PromptBuilder(COMMENTARY_ONE_PERSON)

    line = json.loads(builder.output_example)["lines"][0]
    segment = next(item for item in COMMENTARY_ONE_PERSON.segments if item.id == line["segment"])
    assert line["section"] == segment.kind
    assert builder.segment_for_section(line["section"]) == line["segment"]


def test_custom_prompt_lists_ordered_segment_ids_kinds_counts_and_speakers():
    from app.programs.profiles import ProgramSegment

    profile = replace(
        COMMENTARY_ONE_PERSON,
        segments=(
            ProgramSegment("headline_open", "headline", 0, 1, 2, ("male",)),
            ProgramSegment("headline_wrap", "headline", 1, 2, 3, ("male",)),
            ProgramSegment("daily_corner", "corner", 2, 1, 1, ("male",)),
        ),
    )
    builder = PromptBuilder(profile)
    prompt = builder.build_profile_prompt(
        task_description="台本を作成してください。",
        input_description="記事本文",
    )

    assert prompt.index("headline_open") < prompt.index("headline_wrap") < prompt.index("daily_corner")
    assert "section: `headline`" in prompt
    assert "1〜2行、話者: male" in prompt
    assert "2〜3行、話者: male" in prompt
    assert "同じ kind のセグメントが複数ある場合" in prompt
    assert builder.segment_id_for_output("headline") is None
    assert builder.segment_id_for_output("headline", "headline_wrap") == "headline_wrap"
    with pytest.raises(ValueError, match="multiple segments"):
        builder.segment_for_section("headline")
