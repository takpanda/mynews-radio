"""commentary_dialogue（2人解説）のプロンプトに solo 専用の指示が混入しないことの確認（BEE-554）。"""

import json
from unittest.mock import patch

from app.batch.generate_commentary_script import (
    _load_prompt_template,
    generate_commentary_script,
)
from app.programs.prompt_builder import PromptBuilder
from app.programs.profiles import COMMENTARY_TWO_PERSON

SOLO_ONLY_INSTRUCTION = "1名のみ"
ARTICLE = {"id": 7, "title": "テスト記事", "text": "記事本文です。" * 300}


def _two_speaker_response() -> dict:
    return {
        "title": ARTICLE["title"],
        "subtitle": "二人で読み解く",
        "lines": [
            {"speaker": "male", "text": "今日の記事を紹介します。", "article_id": 7, "section": "intro", "delivery": "neutral"},
            {"speaker": "female", "text": "どこが注目点でしょうか。", "article_id": 7, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "件数は123件と示されています。", "article_id": 7, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "利用者への影響が気になります。", "article_id": 7, "section": "outro", "delivery": "warm"},
        ],
    }


def test_dialogue_template_has_no_solo_only_instructions():
    prompt = _load_prompt_template("dialogue")

    assert SOLO_ONLY_INSTRUCTION not in prompt
    assert "一人語り" not in prompt
    assert "<!-- SOLO_ONLY -->" not in prompt
    assert "<!-- END_SOLO_ONLY -->" not in prompt
    assert "スタイル=dialogue（二人対談）の場合" in prompt
    assert '"speaker": "female"' in prompt


def test_solo_template_keeps_solo_instructions_without_markers():
    prompt = _load_prompt_template("solo")

    assert SOLO_ONLY_INSTRUCTION in prompt
    assert "<!-- SOLO_ONLY -->" not in prompt
    assert "<!-- END_SOLO_ONLY -->" not in prompt
    assert "<!-- DIALOGUE_ONLY -->" not in prompt
    assert "スタイル=dialogue" not in prompt


def test_commentary_dialogue_profile_uses_legacy_prompt_path():
    # 本テストは legacy 経路（既存テンプレート）に対する回帰テスト。経路が変わったら前提を見直す。
    assert PromptBuilder(COMMENTARY_TWO_PERSON).uses_legacy_prompt


def test_commentary_dialogue_generation_prompt_excludes_solo_instructions(tmp_path):
    output = tmp_path / "script.json"

    with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
        instance = mock.return_value
        instance.__enter__.return_value.generate_json.return_value = _two_speaker_response()
        generate_commentary_script(
            str(output), ARTICLE, program_profile=COMMENTARY_TWO_PERSON,
        )

    prompt = instance.__enter__.return_value.generate_json.call_args.args[0]
    assert SOLO_ONLY_INSTRUCTION not in prompt
    assert "一人語り" not in prompt
    assert "スタイル=dialogue（二人対談）の場合" in prompt

    script = json.loads(output.read_text(encoding="utf-8"))
    speakers = {line["speaker"] for line in script["lines"]}
    assert speakers == {"male", "female"}
    assert script["style"] == "dialogue"


def test_solo_generation_prompt_keeps_solo_instructions(tmp_path):
    output = tmp_path / "script.json"
    fake_response = {
        "title": ARTICLE["title"],
        "subtitle": "一人で読み解く",
        "lines": [
            {"speaker": "female", "text": "記事の概要を説明します。", "article_id": 7, "section": "intro", "delivery": "neutral"},
        ],
    }

    with patch("app.batch.generate_commentary_script.OllamaClient") as mock:
        instance = mock.return_value
        instance.__enter__.return_value.generate_json.return_value = fake_response
        generate_commentary_script(str(output), ARTICLE, style="solo", mc_gender="female")

    prompt = instance.__enter__.return_value.generate_json.call_args.args[0]
    assert '話者は "female" 1名のみ' in prompt
    assert "<!-- SOLO_ONLY -->" not in prompt
    assert "スタイル=dialogue" not in prompt
