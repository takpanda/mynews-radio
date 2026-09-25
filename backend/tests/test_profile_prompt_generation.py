import json
from dataclasses import replace
from unittest.mock import patch

from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
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
        cast=(ProgramCastMember("male", "司会", "一人語り"),),
        options=replace(RADIO_TWO_PERSON.options, narrative_arc=False),
        segments=tuple(
            replace(segment, speaker_keys=("male",))
            for segment in RADIO_TWO_PERSON.segments
        ),
    )
    client = _FakeClient({
        "title": "テスト",
        "lines": [
            {"speaker": "male", "text": "冒頭です。", "section": "intro"},
            {"speaker": "male", "text": "一つ目の記事です。", "article_id": 1, "section": "news"},
            {"speaker": "male", "text": "二つ目の記事です。", "article_id": 2, "section": "news"},
            {"speaker": "male", "text": "以上です。", "section": "outro"},
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

    script = json.loads((tmp_path / "script.json").read_text(encoding="utf-8"))
    transitions = [line for line in script["lines"] if line["section"] == "transition"]
    between_articles = [line for line in transitions if line["article_id"] == 2]
    assert len(between_articles) == 1
    assert between_articles[0]["segment"] == "transition"
    assert all(line.get("segment") for line in script["lines"])


def test_commentary_generation_inserts_profile_json_after_template_formatting(tmp_path):
    from app.batch import generate_commentary_script as generation

    profile = replace(
        COMMENTARY_ONE_PERSON,
        id="commentary_custom",
        cast=(ProgramCastMember("male", "カスタム解説者", "専門家"),),
    )
    client = _FakeClient({
        "title": "記事タイトル",
        "lines": [
            {"speaker": "male", "text": "数字は42です。", "article_id": 7, "section": "news"},
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
