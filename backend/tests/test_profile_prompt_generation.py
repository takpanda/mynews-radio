import json
from dataclasses import replace
from unittest.mock import patch

from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
    COMMENTARY_TWO_PERSON,
    ProgramSegment,
    RADIO_TWO_PERSON,
    ProgramCastMember,
)


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_radio_generation_uses_custom_profile_and_segments_added_transitions(tmp_path):
    from app.batch import generate_script as generation

    profile = replace(
        RADIO_TWO_PERSON,
        id="radio_solo_custom",
        name="一人語りラジオ",
        cast=(ProgramCastMember("host", "司会", "一人語り"),),
        options=replace(RADIO_TWO_PERSON.options, narrative_arc=False),
        segments=tuple(
            replace(segment, speaker_keys=("host",))
            for segment in RADIO_TWO_PERSON.segments
        ),
    )
    client = _FakeClient({
        "title": "テスト",
        "lines": [
            {"speaker": "host", "text": "冒頭です。", "section": "intro"},
            {"speaker": "host", "text": "一つ目の記事です。", "article_id": 1, "section": "news"},
            {"speaker": "host", "text": "二つ目の記事です。", "article_id": 2, "section": "news"},
            {"speaker": "host", "text": "以上です。", "section": "outro"},
        ],
    })

    with patch.object(
        generation.ArticleService,
        "fetch_summaries_for_script",
        return_value=[
            {"id": 1, "title": "一つ目", "summary": "一つ目の要約です。"},
            {"id": 2, "title": "二つ目", "summary": "二つ目の要約です。"},
        ],
    ), patch.object(generation, "create_llm_client", return_value=client):
        count = generation.generate_script(
            str(tmp_path / "script.json"),
            program_profile=profile,
            llm_provider="test",
            llm_model="test-model",
        )

    assert count > 0
    prompt = client.prompts[0]
    assert "一人語り" in prompt
    assert "記事間のtransitionは、各記事の間に独立した1行" in prompt
    assert "2人のMC" not in prompt
    assert "交互" not in prompt
    assert 'speaker は "male" または "female" のみ' not in prompt
    assert '"male"' not in prompt
    assert '"female"' not in prompt
    assert "田村" not in prompt
    assert "山口" not in prompt

    script = json.loads((tmp_path / "script.json").read_text(encoding="utf-8"))
    transitions = [line for line in script["lines"] if line["section"] == "transition"]
    between_articles = [line for line in transitions if line["article_id"] == 2]
    assert len(between_articles) == 1
    assert between_articles[0]["segment"] == "transition"
    assert all(line.get("segment") for line in script["lines"])
    assert {line["speaker"] for line in script["lines"]} == {"host"}


def test_commentary_generation_inserts_profile_json_after_template_formatting(tmp_path):
    from app.batch import generate_commentary_script as generation

    profile = replace(
        COMMENTARY_ONE_PERSON,
        id="commentary_custom",
        cast=(ProgramCastMember("analyst", "カスタム解説者", "専門家"),),
        options=replace(COMMENTARY_ONE_PERSON.options, mc_gender="analyst"),
        segments=tuple(
            replace(segment, speaker_keys=("analyst",))
            for segment in COMMENTARY_ONE_PERSON.segments
        ),
    )
    client = _FakeClient({
        "title": "記事タイトル",
        "lines": [
            {"speaker": "analyst", "text": "数字は42です。", "article_id": 7, "section": "news"},
        ],
    })

    with patch.object(generation, "create_llm_client", return_value=client):
        count = generation.generate_commentary_script(
            str(tmp_path / "commentary.json"),
            {"id": 7, "title": "記事タイトル", "text": "本文42です。"},
            program_profile=profile,
            llm_provider="test",
            llm_model="test-model",
        )

    assert count == 1
    assert "カスタム解説者" in client.prompts[0]
    assert '"lines"' in client.prompts[0]
    assert '"speaker": "analyst"' in client.prompts[0]
    script = json.loads((tmp_path / "commentary.json").read_text(encoding="utf-8"))
    assert script["style"] == "solo"
    assert script["mc_gender"] == "analyst"
    assert script["lines"][0]["speaker"] == "analyst"


def test_commentary_style_defaults_from_explicit_dialogue_profile(tmp_path):
    from app.batch import generate_commentary_script as generation

    client = _FakeClient({
        "title": "記事タイトル",
        "lines": [
            {"speaker": "male", "text": "事実は42です。", "article_id": 7, "section": "news"},
            {"speaker": "female", "text": "生活への影響が気になります。", "article_id": 7, "section": "news"},
        ],
    })

    with patch.object(generation, "create_llm_client", return_value=client):
        count = generation.generate_commentary_script(
            str(tmp_path / "dialogue.json"),
            {"id": 7, "title": "記事タイトル", "text": "本文42です。"},
            program_profile=COMMENTARY_TWO_PERSON,
            llm_provider="test",
            llm_model="test-model",
        )

    assert count == 2
    assert "スタイルパラメータ: dialogue" in client.prompts[0]
    script = json.loads((tmp_path / "dialogue.json").read_text(encoding="utf-8"))
    assert script["style"] == "dialogue"
    assert {line["speaker"] for line in script["lines"]} == {"male", "female"}


def test_generation_and_final_validation_report_missing_unknown_and_mismatched_ids(tmp_path):
    from app.batch import generate_commentary_script as generation
    from app.batch.final_validation import validate_final_script

    profile = replace(
        COMMENTARY_ONE_PERSON,
        id="commentary_multiple_features",
        segments=(
            ProgramSegment("headline_open", "headline", 0, 0, 5, ("male",)),
            ProgramSegment("headline_wrap", "headline", 1, 0, 5, ("male",)),
            ProgramSegment("daily_corner", "corner", 2, 0, 5, ("male",)),
        ),
    )
    client = _FakeClient({
        "title": "記事タイトル",
        "lines": [
            {"speaker": "male", "text": "見出しです 42。", "section": "headline", "segment": "headline_open"},
            {"speaker": "male", "text": "IDがありません 42。", "section": "headline"},
            {"speaker": "male", "text": "不明なIDです 42。", "section": "corner", "segment": "unknown_id"},
            {"speaker": "male", "text": "IDとkindが違います 42。", "section": "headline", "segment": "daily_corner"},
        ],
    })

    with patch.object(generation, "create_llm_client", return_value=client):
        generation.generate_commentary_script(
            str(tmp_path / "custom-script.json"),
            {"id": 7, "title": "記事タイトル", "text": "本文42です。"},
            program_profile=profile,
            llm_provider="test",
            llm_model="test-model",
        )

    script = json.loads((tmp_path / "custom-script.json").read_text(encoding="utf-8"))
    assert script["lines"][0]["segment"] == "headline_open"
    assert "segment" not in script["lines"][1]
    assert script["lines"][2]["segment"] == "unknown_id"
    assert script["lines"][3]["segment"] == "daily_corner"
    assert script["lines"][3]["section"] == "headline"

    result = validate_final_script(
        script["lines"],
        program_profile=profile,
        commentary=True,
        style="solo",
    )
    finding_codes = {finding["code"] for finding in result["critical_issues"]}
    assert {"SEGMENT_MISSING", "UNKNOWN_SEGMENT", "SEGMENT_SECTION_MISMATCH"} <= finding_codes
