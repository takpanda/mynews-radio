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
RADIO_CHECK_LINES = [
    {"speaker": "male", "text": "「ニュースのとなり」の時間です。今日もニュースをお届けします。", "article_id": None, "section": "intro", "delivery": "neutral"},
    {"speaker": "female", "text": "今日の話題を順番に見ていきましょう。", "article_id": None, "section": "intro", "delivery": "neutral"},
    {"speaker": "male", "text": "固定ニュースについてお伝えします。", "article_id": 123, "section": "news", "delivery": "neutral"},
    {"speaker": "female", "text": "記事には具体的な数字の123が示されています。", "article_id": 123, "section": "news", "delivery": "questioning"},
    {"speaker": "male", "text": "今日は固定ニュースを取り上げました。", "article_id": None, "section": "outro", "delivery": "warm"},
    {"speaker": "female", "text": "それではまた次回お会いしましょう。", "article_id": None, "section": "outro", "delivery": "warm"},
]
COMMENTARY_SOLO_CHECK_LINES = [
    {"speaker": "male", "text": "記事の概要を説明します。", "article_id": 321, "section": "intro", "delivery": "neutral"},
    {"speaker": "male", "text": "記事には123件の結果が記されています。", "article_id": 321, "section": "news", "delivery": "neutral"},
    {"speaker": "male", "text": "この結果から背景を読み取れます。", "article_id": 321, "section": "news", "delivery": "thoughtful"},
    {"speaker": "male", "text": "今後の動きも注目されます。", "article_id": None, "section": "outro", "delivery": "warm"},
]
COMMENTARY_DIALOGUE_CHECK_LINES = [
    {"speaker": "male", "text": "記事の概要を説明します。", "article_id": 321, "section": "intro", "delivery": "neutral"},
    {"speaker": "female", "text": "どの点が注目されていますか？", "article_id": 321, "section": "intro", "delivery": "questioning"},
    {"speaker": "male", "text": "記事には123件の結果が記されています。", "article_id": 321, "section": "news", "delivery": "neutral"},
    {"speaker": "female", "text": "利用する人への影響が気になります。", "article_id": 321, "section": "news", "delivery": "thoughtful"},
    {"speaker": "male", "text": "条件を確認する必要があります。", "article_id": 321, "section": "news", "delivery": "thoughtful"},
    {"speaker": "female", "text": "情報を確かめて判断したいですね。", "article_id": 321, "section": "news", "delivery": "warm"},
    {"speaker": "female", "text": "記事の要点を振り返りました。", "article_id": None, "section": "outro", "delivery": "warm"},
    {"speaker": "male", "text": "また次回もお聞きください。", "article_id": None, "section": "outro", "delivery": "warm"},
]


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
        "radio_two_person": lint_script(
            RADIO_CHECK_LINES, program_name="ニュースのとなり"
        ),
        "commentary_solo": validate_final_script(
            COMMENTARY_SOLO_CHECK_LINES, commentary=True, style="solo"
        ),
        "commentary_dialogue": validate_final_script(
            COMMENTARY_DIALOGUE_CHECK_LINES, commentary=True, style="dialogue"
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
