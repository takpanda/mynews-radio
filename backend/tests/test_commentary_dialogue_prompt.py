"""commentary_dialogue（2人解説）のプロンプトに solo 専用の指示が混入しないことの確認（BEE-554）。"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.batch.generate_commentary_script import (
    _apply_style_sections,
    _load_prompt_template,
    generate_commentary_script,
)
from app.batch.review_script import _apply_review_solo_policy
from app.db.migration import migrate_prompt_templates
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


FIXTURES = Path(__file__).parent / "fixtures" / "prompts"
PROMPTS = Path(__file__).parents[1] / "app" / "prompts"
REVIEW_SOLO_TEMPLATE = "話者は 1名（{mc_gender}）のみ"
REVIEW_SOLO_INSTRUCTION = "話者は 1名（male）のみ"


def _migrated_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE programs (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE llm_call_logs (id INTEGER PRIMARY KEY, call_id TEXT NOT NULL UNIQUE, episode_id INTEGER)"
    )
    migrate_prompt_templates(conn)
    return conn


def _set_legacy_active(conn, template_key, content):
    """管理画面未編集の既存環境（旧ファイル由来の active 版）を再現する。"""
    conn.execute(
        "UPDATE prompt_versions SET content = ? WHERE status = 'active' AND template_id = ("
        "SELECT id FROM prompt_templates WHERE template_key = ? AND program_id IS NULL)",
        (content, template_key),
    )


def _active_content(conn, template_key):
    return conn.execute(
        "SELECT pv.content FROM prompt_versions pv JOIN prompt_templates pt ON pt.id = pv.template_id "
        "WHERE pt.template_key = ? AND pt.program_id IS NULL AND pv.status = 'active'",
        (template_key,),
    ).fetchone()[0]


def _version_count(conn, template_key):
    return conn.execute(
        "SELECT COUNT(*) FROM prompt_versions pv JOIN prompt_templates pt ON pt.id = pv.template_id "
        "WHERE pt.template_key = ?",
        (template_key,),
    ).fetchone()[0]


def test_legacy_commentary_active_version_is_migrated_for_dialogue():
    conn = _migrated_conn()
    legacy = (FIXTURES / "generate_commentary_script_pre_bee554.md").read_text(encoding="utf-8")
    _set_legacy_active(conn, "generate_commentary_script", legacy)

    migrate_prompt_templates(conn)
    active = _active_content(conn, "generate_commentary_script")
    current = (PROMPTS / "generate_commentary_script.md").read_text(encoding="utf-8")

    assert SOLO_ONLY_INSTRUCTION not in _apply_style_sections(active, "dialogue")
    assert _apply_style_sections(active, "dialogue") == _apply_style_sections(current, "dialogue")
    assert _apply_style_sections(active, "solo") == _apply_style_sections(current, "solo")


def test_legacy_review_active_version_is_migrated_for_dialogue_and_keeps_solo():
    conn = _migrated_conn()
    legacy = (FIXTURES / "review_synthesize_pre_bee554.md").read_text(encoding="utf-8")
    _set_legacy_active(conn, "review_synthesize", legacy)

    migrate_prompt_templates(conn)
    active = _active_content(conn, "review_synthesize")
    current = (PROMPTS / "review_synthesize.md").read_text(encoding="utf-8")

    assert REVIEW_SOLO_TEMPLATE not in _apply_review_solo_policy(active, "dialogue")
    assert _apply_review_solo_policy(active, "dialogue") == _apply_review_solo_policy(current, "dialogue")
    assert _apply_review_solo_policy(active, "solo") == _apply_review_solo_policy(current, "solo")
    assert REVIEW_SOLO_TEMPLATE in _apply_review_solo_policy(active, "solo")


def test_migration_keeps_admin_edits_and_is_idempotent():
    conn = _migrated_conn()
    legacy = (FIXTURES / "generate_commentary_script_pre_bee554.md").read_text(encoding="utf-8")
    edited = legacy + "\n管理画面での追記行\n"
    _set_legacy_active(conn, "generate_commentary_script", edited)

    migrate_prompt_templates(conn)
    versions_after_first = _version_count(conn, "generate_commentary_script")
    active = _active_content(conn, "generate_commentary_script")
    assert "管理画面での追記行" in active
    assert "<!-- SOLO_ONLY -->" in active

    migrate_prompt_templates(conn)
    assert _version_count(conn, "generate_commentary_script") == versions_after_first
    assert _active_content(conn, "generate_commentary_script") == active


def _review_source(style=None):
    source = {
        "date": "2026-11-15",
        "title": "ニュースのとなり",
        "subtitle": "",
        "lines": [
            {"speaker": "male", "text": "記事の概要を説明します。", "article_id": 1, "section": "intro", "delivery": "neutral"},
            {"speaker": "female", "text": "どこが注目でしょうか？", "article_id": 1, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "件数は123件です。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "影響が気になります。", "article_id": None, "section": "outro", "delivery": "warm"},
        ],
    }
    if style is not None:
        source["style"] = style
    return source


def _run_review(tmp_path, source, synth_lines):
    from app.batch.review_script import review_script

    script_path = str(tmp_path / "script.json")
    Path(script_path).write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    output_dir = str(tmp_path / "output")
    prompts = []

    def side_effect(prompt_text, **_kw):
        prompts.append(prompt_text)
        if len(prompts) <= 5:
            return {"overall_score": 7, "issues": [], "general_feedback": ""}
        return {"lines": synth_lines, "revision_summary": "修正しました"}

    client = MagicMock()
    client.generate_json.side_effect = side_effect
    with patch("app.batch.review_script.OllamaClient", return_value=client) as mock_cls:
        mock_cls.return_value.__enter__.return_value = client
        result = review_script(script_path, output_dir)
    return result, prompts[5]


def test_review_synthesis_prompt_for_dialogue_has_no_solo_instruction(tmp_path):
    _, synth_prompt = _run_review(tmp_path, _review_source(style="dialogue"), _review_source()["lines"])

    assert REVIEW_SOLO_INSTRUCTION not in synth_prompt
    assert "一人解説の語り口" not in synth_prompt
    assert '"speaker": "female"' in synth_prompt


def test_review_synthesis_prompt_for_solo_keeps_solo_instruction(tmp_path):
    solo_lines = [dict(line, speaker="male") for line in _review_source()["lines"]]
    _, synth_prompt = _run_review(tmp_path, _review_source(style="solo"), solo_lines)

    assert REVIEW_SOLO_INSTRUCTION in synth_prompt


def test_review_rejects_revision_that_drops_a_speaker(tmp_path):
    single_speaker = [dict(line, speaker="male") for line in _review_source()["lines"]]

    result, _ = _run_review(tmp_path, _review_source(style="dialogue"), single_speaker)

    assert result["revised"] is False


def _version_rows(conn, template_key):
    return conn.execute(
        "SELECT pv.status FROM prompt_versions pv JOIN prompt_templates pt ON pt.id = pv.template_id "
        "WHERE pt.template_key = ? AND pt.program_id IS NULL ORDER BY pv.version",
        (template_key,),
    ).fetchall()


def _legacy_generate():
    return (FIXTURES / "generate_commentary_script_pre_bee554.md").read_text(encoding="utf-8")


def _current_generate():
    return (PROMPTS / "generate_commentary_script.md").read_text(encoding="utf-8")


def test_edited_text_inside_solo_section_is_migrated_and_keeps_edit():
    conn = _migrated_conn()
    edited_legacy = _legacy_generate().replace("語り口は落ち着いて知的", "語り口は明るく親しみやすく")
    _set_legacy_active(conn, "generate_commentary_script", edited_legacy)

    migrate_prompt_templates(conn)
    active = _active_content(conn, "generate_commentary_script")
    current_edited = _current_generate().replace("語り口は落ち着いて知的", "語り口は明るく親しみやすく")

    assert "語り口は明るく親しみやすく" in active
    assert _apply_style_sections(active, "dialogue") == _apply_style_sections(current_edited, "dialogue")
    assert _apply_style_sections(active, "solo") == _apply_style_sections(current_edited, "solo")


def test_changed_section_end_is_not_partially_migrated(caplog):
    conn = _migrated_conn()
    # 開始だけ一致する編集: 終了文言が変わると区間を特定できないため版を変えない
    edited_legacy = _legacy_generate().replace(
        "各 news ラインには最低1件以上の具体的な事実・数字を含める",
        "各 news ラインには事実を1件以上含める",
    )
    _set_legacy_active(conn, "generate_commentary_script", edited_legacy)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)

    assert _version_rows(conn, "generate_commentary_script") == versions_before
    active = _active_content(conn, "generate_commentary_script")
    assert "<!-- SOLO_ONLY -->" not in active
    assert "Skipping solo-only marker migration" in caplog.text


def test_changed_section_heading_is_not_partially_migrated():
    conn = _migrated_conn()
    edited_legacy = _legacy_generate().replace("## スタイル=solo（一人解説）の場合", "## 一人解説の場合")
    _set_legacy_active(conn, "generate_commentary_script", edited_legacy)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)

    assert _version_rows(conn, "generate_commentary_script") == versions_before
    assert "<!-- SOLO_ONLY -->" not in _active_content(conn, "generate_commentary_script")


def test_unbalanced_manual_markers_are_left_untouched():
    conn = _migrated_conn()
    broken = _legacy_generate().replace("## スタイル=solo（一人解説）の場合", "<!-- SOLO_ONLY -->\n## スタイル=solo（一人解説）の場合")
    _set_legacy_active(conn, "generate_commentary_script", broken)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)

    assert _version_rows(conn, "generate_commentary_script") == versions_before
    assert _active_content(conn, "generate_commentary_script") == broken


def test_legacy_solo_prompt_matches_after_marker_removal_for_generate():
    legacy = _legacy_generate()
    assert _apply_style_sections(legacy, "solo") == _apply_style_sections(_current_generate(), "solo")


def test_review_solo_render_matches_legacy_and_keeps_line_breaks():
    legacy = (FIXTURES / "review_synthesize_pre_bee554.md").read_text(encoding="utf-8")
    current = (PROMPTS / "review_synthesize.md").read_text(encoding="utf-8")
    solo = _apply_review_solo_policy(current, "solo")
    dialogue = _apply_review_solo_policy(current, "dialogue")

    # solo は旧版からマーカー行と行内マーカーの除去だけで一致する（行の連結なし）
    assert solo == legacy.replace("<!-- solo -->", "").replace("<!-- END_SOLO -->", "")
    assert "維持する4. " not in solo
    assert "\n4. 元の台本の lines 数" in dialogue
    assert "一人解説の語り口" not in dialogue
    assert REVIEW_SOLO_TEMPLATE not in dialogue
