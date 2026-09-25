import json
from dataclasses import replace

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
