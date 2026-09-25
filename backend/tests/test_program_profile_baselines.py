"""Golden baselines for the three pre-profile prompt and checker paths."""

import json
import os
from pathlib import Path

from app.batch.final_validation import validate_final_script
from app.batch.generate_commentary_script import (
    _build_section_details,
    _calc_suggested_lines,
    _load_prompt_template as load_commentary_template,
)
from app.batch.generate_script import _load_prompt_template as load_radio_template
from app.batch.generate_script import lint_script


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "program_profile_baselines.json"
FIXED_ARTICLE = {
    "id": 321,
    "title": "固定条件の記事タイトル",
    "text": "これはゴールデンテスト用の固定記事本文です。" * 200,
}
FIXED_SUMMARIES = [{
    "id": 123,
    "title": "固定条件のニュース",
    "summary": "固定条件でプロンプトを再現するための要約です。",
}]


def _build_prompt_baselines() -> dict[str, str]:
    radio_prompt = load_radio_template().format(
        narrative_arc_section="",
        summaries_json=json.dumps(FIXED_SUMMARIES, ensure_ascii=False, indent=2),
    )
    prompts = {"radio_two_person": radio_prompt}

    for style in ("solo", "dialogue"):
        mc_gender = "male"
        template = load_commentary_template(style)
        suggested_lines = _calc_suggested_lines(len(FIXED_ARTICLE["text"]), style)
        prompts[f"commentary_{style}"] = template.format(
            style=style,
            mc_gender=mc_gender,
            article_id=FIXED_ARTICLE["id"],
            article_title=FIXED_ARTICLE["title"],
            suggested_lines_count=suggested_lines,
            section_details=_build_section_details(suggested_lines, style),
            article_json=json.dumps(
                {key: FIXED_ARTICLE[key] for key in ("id", "title", "text")},
                ensure_ascii=False,
                indent=2,
            ),
        )
    return prompts


def _build_checker_baselines() -> dict:
    return {
        "radio_two_person": lint_script([], program_name="ニュースのとなり"),
        "commentary_solo": validate_final_script(
            [], commentary=True, style="solo"
        ),
        "commentary_dialogue": validate_final_script(
            [], commentary=True, style="dialogue"
        ),
    }


def test_existing_prompts_and_checker_results_match_golden_baselines():
    actual = {
        "prompts": _build_prompt_baselines(),
        "checker_results": _build_checker_baselines(),
    }
    if os.environ.get("UPDATE_PROGRAM_PROFILE_BASELINES") == "1":
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert actual == expected
