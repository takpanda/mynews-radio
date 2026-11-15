"""commentary_dialogue（2人解説）のプロンプトに solo 専用の指示が混入しないことの確認（BEE-554）。"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


def _patch_db(conn):
    """app.prompts.service の DB 接続を、テスト用の接続へ差し替える。"""
    from contextlib import contextmanager

    @contextmanager
    def _connection():
        yield conn

    return patch("app.prompts.service.get_db_connection", side_effect=lambda: _connection())


def _no_patch():
    from contextlib import nullcontext

    return nullcontext()


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


def _run_review(tmp_path, source, synth_lines, conn=None):
    from app.batch.review_script import review_script

    tmp_path.mkdir(parents=True, exist_ok=True)
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
    with _patch_db(conn) if conn is not None else _no_patch(), \
            patch("app.batch.review_script.OllamaClient", return_value=client) as mock_cls:
        mock_cls.return_value.__enter__.return_value = client
        result = review_script(script_path, output_dir)
    return result, prompts


def test_review_synthesis_prompt_for_dialogue_has_no_solo_instruction(tmp_path):
    _, prompts = _run_review(tmp_path, _review_source(style="dialogue"), _review_source()["lines"])
    synth_prompt = prompts[5]

    assert REVIEW_SOLO_INSTRUCTION not in synth_prompt
    assert "一人解説の語り口" not in synth_prompt
    assert '"speaker": "female"' in synth_prompt


def test_review_synthesis_prompt_for_solo_keeps_solo_instruction(tmp_path):
    solo_lines = [dict(line, speaker="male") for line in _review_source()["lines"]]
    _, prompts = _run_review(tmp_path, _review_source(style="solo"), solo_lines)
    synth_prompt = prompts[5]

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
    assert "Solo-only sections not identified" in caplog.text


def test_changed_section_heading_is_not_partially_migrated():
    conn = _migrated_conn()
    edited_legacy = _legacy_generate().replace("## スタイル=solo（一人解説）の場合", "## 一人解説の場合")
    _set_legacy_active(conn, "generate_commentary_script", edited_legacy)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)

    assert _version_rows(conn, "generate_commentary_script") == versions_before
    assert "<!-- SOLO_ONLY -->" not in _active_content(conn, "generate_commentary_script")


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


def _generate_dialogue(tmp_path, conn=None, style="dialogue", episode_id=None):
    """DB の active 版を使って生成し、送信プロンプトを返す。"""
    output = tmp_path / "script.json"
    with _patch_db(conn) if conn is not None else _no_patch(), \
            patch("app.batch.generate_commentary_script.infer_episode_id", return_value=episode_id), \
            patch("app.batch.generate_commentary_script.OllamaClient") as mock:
        instance = mock.return_value.__enter__.return_value
        instance.generate_json.return_value = _two_speaker_response()
        generate_commentary_script(
            str(output), ARTICLE, style=style,
            program_profile=COMMENTARY_TWO_PERSON if style == "dialogue" else None,
            mc_gender="female",
        )
    return instance.generate_json.call_args.args[0]


def _edited_end_anchor(text):
    return text.replace(
        "各 news ラインには最低1件以上の具体的な事実・数字を含める",
        "各 news ラインには事実を1件以上含める",
    )


def test_dialogue_generation_refuses_edited_legacy_template_and_recovers_after_fix(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    _set_legacy_active(conn, "generate_commentary_script", _edited_end_anchor(_legacy_generate()))

    with pytest.raises(SoloSectionsUnmarkedError):
        _generate_dialogue(tmp_path / "a", conn)

    # 修正後（区間の付いた版へ戻す）の再試行は成功し、単一話者の指示は含まれない
    _set_legacy_active(conn, "generate_commentary_script", _current_generate())
    prompt = _generate_dialogue(tmp_path / "b", conn)
    assert SOLO_ONLY_INSTRUCTION not in prompt
    assert "スタイル=dialogue（二人対談）の場合" in prompt


def test_solo_generation_is_not_affected_by_unidentifiable_template(tmp_path):
    conn = _migrated_conn()
    _set_legacy_active(conn, "generate_commentary_script", _edited_end_anchor(_legacy_generate()))

    prompt = _generate_dialogue(tmp_path, conn, style="solo")

    assert '話者は "female" 1名のみ' in prompt


def test_program_scoped_edited_template_only_blocks_its_own_dialogue(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    program_id = COMMENTARY_TWO_PERSON.id
    conn.execute("INSERT INTO programs (id) VALUES (?)", (program_id,))
    common = conn.execute(
        "SELECT id, required_variables, allowed_variables FROM prompt_templates "
        "WHERE template_key = 'generate_commentary_script' AND program_id IS NULL"
    ).fetchone()
    conn.execute(
        "INSERT INTO prompt_templates (template_key, program_id, required_variables, allowed_variables) "
        "VALUES ('generate_commentary_script', ?, ?, ?)",
        (program_id, common["required_variables"], common["allowed_variables"]),
    )
    program_template_id = conn.execute(
        "SELECT id FROM prompt_templates WHERE template_key = 'generate_commentary_script' AND program_id = ?",
        (program_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, ?, 'active')",
        (program_template_id, _edited_end_anchor(_legacy_generate())),
    )

    # この番組の dialogue だけ停止し、共通版（他番組）の dialogue は影響を受けない
    with pytest.raises(SoloSectionsUnmarkedError):
        _generate_dialogue(tmp_path / "scoped", conn, episode_id=1)
    prompt = _generate_dialogue(tmp_path / "common", conn, episode_id=None)
    assert SOLO_ONLY_INSTRUCTION not in prompt


def test_review_refuses_edited_legacy_template_for_dialogue(tmp_path):
    conn = _migrated_conn()
    edited = (FIXTURES / "review_synthesize_pre_bee554.md").read_text(encoding="utf-8").replace(
        "元の台本に含まれる数値・金額・日時・固有名詞をぼかさず元の値をそのまま使う",
        "元の台本の数値を使う",
    )
    _set_legacy_active(conn, "review_synthesize", edited)

    result, prompts = _run_review(tmp_path, _review_source(style="dialogue"), _review_source()["lines"], conn=conn)

    assert result["revised"] is False
    assert len(prompts) == 5  # synthesis は送信されない
    assert all(REVIEW_SOLO_INSTRUCTION not in p for p in prompts)


def test_review_solo_still_runs_with_edited_legacy_template(tmp_path):
    conn = _migrated_conn()
    edited = (FIXTURES / "review_synthesize_pre_bee554.md").read_text(encoding="utf-8").replace(
        "元の台本に含まれる数値・金額・日時・固有名詞をぼかさず元の値をそのまま使う",
        "元の台本の数値を使う",
    )
    _set_legacy_active(conn, "review_synthesize", edited)
    solo_lines = [dict(line, speaker="male") for line in _review_source()["lines"]]

    _, prompts = _run_review(tmp_path, _review_source(style="solo"), solo_lines, conn=conn)

    assert len(prompts) == 6
    assert REVIEW_SOLO_INSTRUCTION in prompts[5]


SOLO_OPEN = "<!-- SOLO_ONLY -->"
SOLO_CLOSE = "<!-- END_SOLO_ONLY -->"
ADMIN_SOLO = "管理者追加の一人用指示です。"


def test_partially_marked_template_is_completed_by_migration():
    conn = _migrated_conn()
    one_line_only = _legacy_generate().replace(
        '- soloの場合: speaker は "{mc_gender}" のみ\n',
        f'{SOLO_OPEN}\n- soloの場合: speaker は "{{mc_gender}}" のみ\n{SOLO_CLOSE}\n',
    )
    _set_legacy_active(conn, "generate_commentary_script", one_line_only)

    migrate_prompt_templates(conn)

    assert _active_content(conn, "generate_commentary_script") == _current_generate()


def test_reversed_and_nested_markers_are_not_migrated_and_dialogue_is_refused(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    broken = _legacy_generate().replace(
        "## スタイル=solo（一人解説）の場合\n",
        f"{SOLO_CLOSE}\n{SOLO_OPEN}\n{SOLO_OPEN}\n## スタイル=solo（一人解説）の場合\n",
    )
    _set_legacy_active(conn, "generate_commentary_script", broken)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)

    assert _version_rows(conn, "generate_commentary_script") == versions_before
    assert _active_content(conn, "generate_commentary_script") == broken
    with pytest.raises(SoloSectionsUnmarkedError):
        _generate_dialogue(tmp_path, conn)


def test_admin_added_solo_section_survives_migration_and_stays_out_of_dialogue(tmp_path):
    conn = _migrated_conn()
    admin_block = f"{SOLO_OPEN}\n{ADMIN_SOLO}\n{SOLO_CLOSE}\n"
    _set_legacy_active(conn, "generate_commentary_script", _legacy_generate() + "\n" + admin_block)

    migrate_prompt_templates(conn)
    active = _active_content(conn, "generate_commentary_script")

    assert active == _current_generate() + "\n" + admin_block
    dialogue_prompt = _generate_dialogue(tmp_path / "dialogue", conn)
    assert ADMIN_SOLO not in dialogue_prompt
    assert SOLO_ONLY_INSTRUCTION not in dialogue_prompt
    solo_prompt = _generate_dialogue(tmp_path / "solo", conn, style="solo")
    assert ADMIN_SOLO in solo_prompt


def test_admin_added_unmarked_solo_text_refuses_dialogue_and_names_the_line(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    _set_legacy_active(conn, "generate_commentary_script", _legacy_generate() + "\n話者は1名のみで語ってください。\n")

    with pytest.raises(SoloSectionsUnmarkedError, match="1名のみ"):
        _generate_dialogue(tmp_path, conn)


def _mark_edited_generate(text):
    """管理者が編集後の solo 区間を手で囲む手順を再現する。"""
    text = text.replace("## スタイル=solo（一人解説）の場合\n", f"{SOLO_OPEN}\n## スタイル=solo（一人解説）の場合\n")
    text = text.replace("各 news ラインには事実を1件以上含める\n", f"各 news ラインには事実を1件以上含める\n{SOLO_CLOSE}\n")
    text = text.replace("**solo の場合（基本フォーマット）**:\n", f"{SOLO_OPEN}\n**solo の場合（基本フォーマット）**:\n")
    text = text.replace("}}\n\n<!-- DIALOGUE_ONLY -->", f"}}\n{SOLO_CLOSE}\n\n<!-- DIALOGUE_ONLY -->")
    line = '- soloの場合: speaker は "{mc_gender}" のみ\n'
    return text.replace(line, f"{SOLO_OPEN}\n{line}{SOLO_CLOSE}\n")


def test_edited_boundary_is_refused_then_recovered_by_marking_by_hand(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    edited = _edited_end_anchor(_legacy_generate())
    _set_legacy_active(conn, "generate_commentary_script", edited)
    versions_before = _version_rows(conn, "generate_commentary_script")

    migrate_prompt_templates(conn)
    assert _version_rows(conn, "generate_commentary_script") == versions_before
    with pytest.raises(SoloSectionsUnmarkedError, match="行 "):
        _generate_dialogue(tmp_path / "before", conn)

    # 管理者が囲んだ後は、編集内容を保ったまま dialogue が通り、solo にも編集内容が残る
    marked = _mark_edited_generate(edited)
    _set_legacy_active(conn, "generate_commentary_script", marked)
    dialogue_prompt = _generate_dialogue(tmp_path / "after", conn)
    assert SOLO_ONLY_INSTRUCTION not in dialogue_prompt
    assert "事実を1件以上含める" not in dialogue_prompt
    solo_prompt = _generate_dialogue(tmp_path / "solo", conn, style="solo")
    assert "事実を1件以上含める" in solo_prompt


def _mark_edited_review(text):
    text = text.replace("## solo モードのMCについて\n", f"{SOLO_OPEN}\n## solo モードのMCについて\n")
    text = text.replace("元の台本の数値を使う\n", f"元の台本の数値を使う\n{SOLO_CLOSE}\n")
    text = text.replace("<!-- solo -->", SOLO_OPEN).replace("<!-- END_SOLO -->", SOLO_CLOSE)
    text = text.replace("## 出力例（solo モード）\n", f"{SOLO_OPEN}\n## 出力例（solo モード）\n")
    text = text.replace("}}\n\n## 共通条件", f"}}\n{SOLO_CLOSE}\n\n## 共通条件")
    text = text.replace("## solo モードの条件\n", f"{SOLO_OPEN}\n## solo モードの条件\n")
    return text + SOLO_CLOSE + "\n"


def test_review_edited_boundary_is_refused_then_recovered_by_marking_by_hand(tmp_path):
    conn = _migrated_conn()
    edited = (FIXTURES / "review_synthesize_pre_bee554.md").read_text(encoding="utf-8").replace(
        "元の台本に含まれる数値・金額・日時・固有名詞をぼかさず元の値をそのまま使う",
        "元の台本の数値を使う",
    )
    _set_legacy_active(conn, "review_synthesize", edited)

    result, prompts = _run_review(tmp_path / "before", _review_source(style="dialogue"), _review_source()["lines"], conn=conn)
    assert result["revised"] is False and len(prompts) == 5

    _set_legacy_active(conn, "review_synthesize", _mark_edited_review(edited))
    result, prompts = _run_review(tmp_path / "after", _review_source(style="dialogue"), _review_source()["lines"], conn=conn)
    assert len(prompts) == 6
    assert REVIEW_SOLO_INSTRUCTION not in prompts[5]
    assert "元の台本の数値を使う" not in prompts[5]


def test_common_refusal_does_not_block_program_scoped_dialogue(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    _set_legacy_active(conn, "generate_commentary_script", _edited_end_anchor(_legacy_generate()))
    program_id = COMMENTARY_TWO_PERSON.id
    conn.execute("INSERT INTO programs (id) VALUES (?)", (program_id,))
    common = conn.execute(
        "SELECT required_variables, allowed_variables FROM prompt_templates "
        "WHERE template_key = 'generate_commentary_script' AND program_id IS NULL"
    ).fetchone()
    conn.execute(
        "INSERT INTO prompt_templates (template_key, program_id, required_variables, allowed_variables) "
        "VALUES ('generate_commentary_script', ?, ?, ?)",
        (program_id, common["required_variables"], common["allowed_variables"]),
    )
    template_id = conn.execute(
        "SELECT id FROM prompt_templates WHERE template_key = 'generate_commentary_script' AND program_id = ?",
        (program_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO prompt_versions (template_id, version, content, status) VALUES (?, 1, ?, 'active')",
        (template_id, _current_generate()),
    )

    with pytest.raises(SoloSectionsUnmarkedError):
        _generate_dialogue(tmp_path / "common", conn, episode_id=None)
    prompt = _generate_dialogue(tmp_path / "program", conn, episode_id=1)
    assert SOLO_ONLY_INSTRUCTION not in prompt


def _generate_template_with_tail(tail):
    return _current_generate() + tail


def test_marker_closed_before_solo_instruction_on_same_line_is_refused(tmp_path):
    from app.prompts.solo_sections import SoloSectionsUnmarkedError

    conn = _migrated_conn()
    _set_legacy_active(
        conn, "generate_commentary_script",
        _generate_template_with_tail(f"\n{SOLO_OPEN}\n本文\n{SOLO_CLOSE}話者は1名のみ\n"),
    )

    with pytest.raises(SoloSectionsUnmarkedError, match="1名のみ"):
        _generate_dialogue(tmp_path, conn)


def test_solo_instruction_inside_same_line_markers_is_sent_to_solo_only(tmp_path):
    conn = _migrated_conn()
    _set_legacy_active(
        conn, "generate_commentary_script",
        _generate_template_with_tail(f"\n前文{SOLO_OPEN}話者は1名のみ{SOLO_CLOSE}後文\n"),
    )

    dialogue_prompt = _generate_dialogue(tmp_path / "dialogue", conn)
    solo_prompt = _generate_dialogue(tmp_path / "solo", conn, style="solo")

    assert "前文" in dialogue_prompt and "後文" in dialogue_prompt
    assert SOLO_ONLY_INSTRUCTION not in dialogue_prompt
    assert "前文" in solo_prompt and "話者は1名のみ" in solo_prompt


def test_review_refuses_solo_instruction_after_closing_marker(tmp_path):
    conn = _migrated_conn()
    tail = f"\n{SOLO_OPEN}\n本文\n{SOLO_CLOSE}話者は 1名（{{mc_gender}}）のみ\n"
    _set_legacy_active(conn, "review_synthesize", _current_review() + tail)

    result, prompts = _run_review(tmp_path, _review_source(style="dialogue"), _review_source()["lines"], conn=conn)

    assert result["revised"] is False
    assert len(prompts) == 5
    assert all(REVIEW_SOLO_INSTRUCTION not in p for p in prompts)


def test_review_sends_inline_solo_instruction_only_to_solo(tmp_path):
    conn = _migrated_conn()
    tail = f"\n前文{SOLO_OPEN}話者は 1名（{{mc_gender}}）のみ{SOLO_CLOSE}後文\n"
    _set_legacy_active(conn, "review_synthesize", _current_review() + tail)

    _, dialogue_prompts = _run_review(tmp_path / "dialogue", _review_source(style="dialogue"), _review_source()["lines"], conn=conn)
    _, solo_prompts = _run_review(tmp_path / "solo", _review_source(style="solo"), _review_source()["lines"], conn=conn)

    assert len(dialogue_prompts) == 6 and len(solo_prompts) == 6
    assert "前文" in dialogue_prompts[5] and "後文" in dialogue_prompts[5]
    assert REVIEW_SOLO_INSTRUCTION not in dialogue_prompts[5]
    assert REVIEW_SOLO_INSTRUCTION in solo_prompts[5]


def _current_review():
    return (PROMPTS / "review_synthesize.md").read_text(encoding="utf-8")


MIXED_HEAD = (
    f"{SOLO_OPEN}\n個別の指示{SOLO_CLOSE}後文を維持\n"
    "共通の指示を維持\n"
)


def test_mixed_marker_layout_keeps_shared_text_in_dialogue_generation(tmp_path):
    conn = _migrated_conn()
    _set_legacy_active(conn, "generate_commentary_script", MIXED_HEAD + _current_generate())

    dialogue_prompt = _generate_dialogue(tmp_path / "dialogue", conn)
    solo_prompt = _generate_dialogue(tmp_path / "solo", conn, style="solo")

    assert "後文を維持" in dialogue_prompt and "共通の指示を維持" in dialogue_prompt
    assert "個別の指示" not in dialogue_prompt
    assert SOLO_ONLY_INSTRUCTION not in dialogue_prompt
    assert "個別の指示" in solo_prompt and "後文を維持" in solo_prompt
    assert SOLO_ONLY_INSTRUCTION in solo_prompt


def test_mixed_marker_layout_keeps_shared_text_in_review(tmp_path):
    conn = _migrated_conn()
    _set_legacy_active(conn, "review_synthesize", MIXED_HEAD + _current_review())

    _, dialogue_prompts = _run_review(tmp_path / "dialogue", _review_source(style="dialogue"), _review_source()["lines"], conn=conn)
    _, solo_prompts = _run_review(tmp_path / "solo", _review_source(style="solo"), _review_source()["lines"], conn=conn)

    assert len(dialogue_prompts) == 6 and len(solo_prompts) == 6
    assert "後文を維持" in dialogue_prompts[5] and "共通の指示を維持" in dialogue_prompts[5]
    assert "個別の指示" not in dialogue_prompts[5]
    assert REVIEW_SOLO_INSTRUCTION not in dialogue_prompts[5]
    assert "個別の指示" in solo_prompts[5]
    assert REVIEW_SOLO_INSTRUCTION in solo_prompts[5]


def test_whole_line_block_followed_by_default_section_is_removed_cleanly():
    from app.prompts.solo_sections import strip_solo_only_sections

    text = f"前行\n{SOLO_OPEN}\n個別\n{SOLO_CLOSE}\n共通\n{SOLO_OPEN}\n区間2\n{SOLO_CLOSE}\n末尾\n"

    assert strip_solo_only_sections(text) == "前行\n共通\n末尾\n"
