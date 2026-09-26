"""生成経路から選択済みプロンプト版IDがLLMログ文脈へ渡ることを確認する。"""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock


class _ContextClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def generate_json(self, prompt):
        self.calls.append((prompt, dict(self._generation_context)))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _install_render_prompt(monkeypatch, module, source="program"):
    rendered = []

    def render(template_key, variables, *, program_id=None):
        version_id = 500 + len(rendered)
        rendered.append((template_key, program_id, variables, version_id))
        return SimpleNamespace(
            template_key=template_key,
            text=f"rendered:{template_key}",
            source=source,
            version_id=version_id,
        )

    monkeypatch.setattr(module, "render_prompt", render)
    return rendered


def test_radio_arc_and_script_versions_reach_call_context(monkeypatch, tmp_path):
    from app.batch import generate_script as generation
    from app.programs.profiles import RADIO_TWO_PERSON

    profile = replace(
        RADIO_TWO_PERSON,
        options=replace(RADIO_TWO_PERSON.options, narrative_arc=True),
    )
    client = _ContextClient([
        {"article_order": [1, 2], "discussion_article_id": 2, "bridges": []},
        {"title": "test", "lines": [
            {"speaker": "male", "text": "「ニュースのとなり」の時間です。", "section": "intro"},
            {"speaker": "female", "text": "今日の話題です。", "section": "intro"},
            {"speaker": "male", "text": "記事1です。", "article_id": 1, "section": "news"},
            {"speaker": "male", "text": "記事2です。", "article_id": 2, "section": "news"},
            {"speaker": "male", "text": "以上です。", "section": "outro"},
            {"speaker": "female", "text": "また明日。", "section": "outro"},
        ]},
    ])
    rendered = _install_render_prompt(monkeypatch, generation)
    monkeypatch.setattr(generation, "create_llm_client", lambda *_args: client)
    monkeypatch.setattr(
        generation.ArticleService,
        "fetch_summaries_for_script",
        lambda *_args, **_kwargs: [
            {"id": 1, "title": "one", "summary": "one"},
            {"id": 2, "title": "two", "summary": "two"},
        ],
    )
    monkeypatch.setenv("SCRIPT_LINT_RETRIES", "1")

    generation.generate_script(
        str(tmp_path / "episodes" / "77" / "script.json"),
        program_profile=profile,
        llm_provider="test",
        llm_model="model",
    )

    assert [(key, program_id) for key, program_id, *_ in rendered] == [
        ("generate_narrative_arc", profile.id),
        ("generate_radio_script", profile.id),
    ]
    assert [context["prompt_version_id"] for _, context in client.calls] == [500, 501]


def test_radio_without_episode_uses_common_scope_for_default_profile(monkeypatch, tmp_path):
    from app.batch import generate_script as generation

    client = _ContextClient([{"article_order": [1], "discussion_article_id": 1, "bridges": []}, {"title": "test", "lines": [
        {"speaker": "male", "text": "「ニュースのとなり」の時間です。", "section": "intro"},
        {"speaker": "female", "text": "今日の話題です。", "section": "intro"},
        {"speaker": "male", "text": "記事です。", "article_id": 1, "section": "news"},
        {"speaker": "male", "text": "以上です。", "section": "outro"},
        {"speaker": "female", "text": "また明日。", "section": "outro"},
    ]}])
    rendered = _install_render_prompt(monkeypatch, generation)
    monkeypatch.setattr(generation, "create_llm_client", lambda *_args: client)
    monkeypatch.setattr(
        generation.ArticleService,
        "fetch_summaries_for_script",
        lambda *_args, **_kwargs: [{"id": 1, "title": "one", "summary": "one"}],
    )
    monkeypatch.setenv("SCRIPT_LINT_RETRIES", "1")

    generation.generate_script(
        str(tmp_path / "standalone-script.json"),
        llm_provider="test",
        llm_model="model",
    )

    assert [(key, program_id) for key, program_id, *_ in rendered] == [
        ("generate_narrative_arc", None), ("generate_radio_script", None),
    ]
    assert [context["prompt_version_id"] for _, context in client.calls] == [500, 501]


def test_profile_prompt_includes_requested_draft_version(monkeypatch, tmp_path):
    from app.batch import generate_script as generation
    from app.db.connection import get_db_connection
    from app.programs.profiles import ProgramCastMember, ProgramOptions, ProgramProfile, ProgramSegment
    from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS

    profile = ProgramProfile(
        id="radio_draft_profile", name="一人番組", kind="radio",
        cast=(ProgramCastMember(key="host", name="司会"),),
        segments=(
            ProgramSegment("intro", "intro", 0, 1, 1, ("host",)),
            ProgramSegment("news", "news", 1, 1, 2, ("host",)),
            ProgramSegment("outro", "outro", 2, 1, 1, ("host",)),
        ),
        options=ProgramOptions(narrative_arc=False),
    )
    definition = PROMPT_TEMPLATE_DEFINITIONS["generate_radio_script"]
    with get_db_connection() as conn:
        template_id = conn.execute(
            "INSERT INTO prompt_templates(template_key, program_id, required_variables, allowed_variables) "
            "VALUES (?, ?, ?, ?)",
            ("generate_radio_script", profile.id, json.dumps(definition["required_variables"]),
             json.dumps(definition["allowed_variables"])),
        ).lastrowid
        version_id = conn.execute(
            "INSERT INTO prompt_versions(template_id, version, content, status) VALUES (?, 1, ?, 'draft')",
            (template_id, "DRAFT_PROMPT_MARKER: follow this draft rule\n{narrative_arc_section}\n{summaries_json}"),
        ).lastrowid

    client = _ContextClient([{"title": "test", "lines": [
        {"speaker": "host", "text": "記事を説明します。", "article_id": 1,
         "section": "news", "segment": "news"},
    ]}])
    monkeypatch.setattr(generation, "create_llm_client", lambda *_args: client)
    monkeypatch.setattr(
        generation.ArticleService, "fetch_summaries_for_script",
        lambda *_args, **_kwargs: [{"id": 1, "title": "article", "summary": "summary"}],
    )
    monkeypatch.setattr(generation, "lint_script", lambda *_args, **_kwargs: [])

    generation.generate_script(
        str(tmp_path / "profile-draft.json"), program_profile=profile,
        prompt_version_id=version_id, use_program_prompt_scope=True, mark_articles=False,
        llm_provider="test", llm_model="model",
    )

    assert "DRAFT_PROMPT_MARKER: follow this draft rule" in client.calls[0][0]
    assert client.calls[0][1]["prompt_version_id"] == version_id


def test_commentary_without_episode_uses_common_scope_and_logs_version(monkeypatch, tmp_path):
    from app.batch import generate_commentary_script as generation

    client = _ContextClient([{"title": "title", "lines": [
        {"speaker": "male", "text": "本文には42があります。", "article_id": 1, "section": "news"},
    ]}])
    rendered = _install_render_prompt(monkeypatch, generation)
    monkeypatch.setattr(generation, "create_llm_client", lambda *_args: client)

    generation.generate_commentary_script(
        str(tmp_path / "commentary.json"),
        {"id": 1, "title": "title", "text": "本文には42があります。"},
        style="solo",
        llm_provider="test",
        llm_model="model",
    )

    assert len(rendered) == 1
    assert rendered[0][0] == "generate_commentary_script"
    assert rendered[0][1] is None
    assert client.calls[0][1]["prompt_version_id"] == rendered[0][3]


def test_summary_program_scope_and_version_reach_call_context(monkeypatch, tmp_path):
    from app.batch import summarize_articles as summary

    client = _ContextClient([{"summary": "summary", "category": "general"}])
    rendered = _install_render_prompt(monkeypatch, summary)
    service = Mock()
    service.fetch_new_articles.return_value = [{
        "id": 9, "title": "title", "source": "source", "url": "url",
        "published_at": "date", "text": "x" * 120,
    }]
    monkeypatch.setattr(summary, "ArticleService", lambda: service)
    monkeypatch.setattr(summary, "OllamaClient", lambda *_args: client)
    monkeypatch.setattr(summary, "program_id_for_episode", lambda episode_id: "program-summary")
    monkeypatch.setattr(
        summary,
        "get_settings",
        lambda: SimpleNamespace(summary_article_max_chars=4000, ollama_base_url="url", ollama_model="model"),
    )

    summary.summarize_articles(str(tmp_path / "episodes" / "77" / "summaries.json"))

    assert rendered[0][0:2] == ("summarize_article", "program-summary")
    assert client.calls[0][1]["prompt_version_id"] == rendered[0][3]


def test_review_directors_and_synthesis_use_program_scope_and_log_each_version(monkeypatch, tmp_path):
    from app.batch import review_script as review

    source = {
        "program_profile_id": "radio_tech_news",
        "style": "solo",
        "mc_gender": "male",
        "title": "title",
        "lines": [{"speaker": "male", "text": "本文です。", "section": "news", "article_id": 1}],
    }
    source_path = tmp_path / "episodes" / "77" / "script.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "reviewed"
    output_dir.mkdir()
    client = _ContextClient([{"overall_score": 7, "issues": []}])
    rendered = _install_render_prompt(monkeypatch, review)
    monkeypatch.setattr(review, "OllamaClient", lambda *_args: client)
    monkeypatch.setattr(review, "program_id_for_episode", lambda _episode_id: "program-review")

    review.review_script(str(source_path), str(output_dir))

    assert [key for key, *_ in rendered] == [
        "review_genius_director", "review_beginner_director", "review_worried_director",
        "review_positive_director", "review_radio_director", "review_synthesize",
    ]
    assert all(program_id == "program-review" for _, program_id, *_ in rendered)
    assert [context["prompt_version_id"] for _, context in client.calls] == [
        item[3] for item in rendered
    ]


def test_category_uses_episode_program_scope_and_logs_selected_version(monkeypatch, tmp_path):
    from app.services import episode_category_service as category

    script_path = tmp_path / "episodes" / "77" / "script.json"
    script_path.parent.mkdir(parents=True)
    script_path.write_text(json.dumps({"lines": [{"text": "AI news"}]}), encoding="utf-8")
    summaries_path = script_path.with_name("summaries.json")
    summaries_path.write_text("[]", encoding="utf-8")
    client = _ContextClient([{"categories": ["AI・先端技術"]}])
    rendered = _install_render_prompt(monkeypatch, category)
    monkeypatch.setattr(category, "program_id_for_episode", lambda _episode_id: "program-category")

    class ClientFactory:
        def __init__(self, *_args, **_kwargs):
            pass
        def __enter__(self):
            return client
        def __exit__(self, *_args):
            return False

    assert category.select_episode_categories(
        str(script_path), str(summaries_path), client_factory=ClientFactory
    ) == ["AI・先端技術"]

    assert rendered[0][0:2] == ("category", "program-category")
    assert client.calls[0][1]["prompt_version_id"] == rendered[0][3]
