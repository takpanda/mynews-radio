import json

from app.db.connection import get_db_connection


def _template_id(key="category", program_id=None):
    with get_db_connection() as conn:
        from app.db.migration import migrate_prompt_templates
        migrate_prompt_templates(conn)
        return conn.execute(
            "SELECT id FROM prompt_templates WHERE template_key = ? AND program_id IS ?",
            (key, program_id),
        ).fetchone()[0]


def _episode(episode_id=71, program_id="radio-test"):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO programs(id, name, kind, definition) VALUES (?, ?, 'radio', '{}')",
            (program_id, "Test Radio"),
        )
        conn.execute(
            "INSERT INTO episodes(id, episode_date, program_id) VALUES (?, '2026-09-01', ?)",
            (episode_id, program_id),
        )
    from app.api import admin_prompts
    (admin_prompts.EPISODES_DIR / str(episode_id)).mkdir(parents=True)
    (admin_prompts.EPISODES_DIR / str(episode_id) / "summaries.json").write_text(
        json.dumps([{"id": 1, "title": "Test article"}], ensure_ascii=False), encoding="utf-8"
    )


def test_prompt_version_draft_validation_activation_conflict_and_rollback(client):
    prompt_id = _template_id()
    assert client.get("/admin/prompts").status_code == 200
    assert client.post(f"/admin/prompts/{prompt_id}/versions", json={"content": "{source}"}).status_code == 422
    draft = client.post(
        f"/admin/prompts/{prompt_id}/versions", json={"content": "preview {source}: {categories}"}
    )
    assert draft.status_code == 201
    first_id = draft.json()["id"]
    with get_db_connection() as conn:
        active_id = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (prompt_id,)
        ).fetchone()[0]
        before_versions = [tuple(row) for row in conn.execute(
            "SELECT id, version, status FROM prompt_versions WHERE template_id = ? ORDER BY id", (prompt_id,)
        )]
        before_rollbacks = conn.execute(
            "SELECT COUNT(*) FROM prompt_version_audit_events WHERE action = 'rollback'"
        ).fetchone()[0]

    invalid_rollback = client.post(
        f"/admin/prompts/versions/{first_id}/rollback",
        json={"change_note": "draft is not rollback source", "expected_active_version_id": active_id},
    )
    assert invalid_rollback.status_code == 409
    with get_db_connection() as conn:
        after_versions = [tuple(row) for row in conn.execute(
            "SELECT id, version, status FROM prompt_versions WHERE template_id = ? ORDER BY id", (prompt_id,)
        )]
        after_rollbacks = conn.execute(
            "SELECT COUNT(*) FROM prompt_version_audit_events WHERE action = 'rollback'"
        ).fetchone()[0]
    assert after_versions == before_versions
    assert after_rollbacks == before_rollbacks

    conflict = client.post(
        f"/admin/prompts/versions/{first_id}/activate",
        json={"change_note": "conflict", "expected_active_version_id": active_id + 1},
    )
    assert conflict.status_code == 409
    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM prompt_versions WHERE id = ?", (first_id,)).fetchone()[0] == "draft"
        assert conn.execute("SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (prompt_id,)).fetchone()[0] == active_id

    activated = client.post(
        f"/admin/prompts/versions/{first_id}/activate",
        json={"change_note": "preview activation", "expected_active_version_id": active_id},
    )
    assert activated.status_code == 200
    rollback = client.post(
        f"/admin/prompts/versions/{active_id}/rollback",
        json={"change_note": "restore original", "expected_active_version_id": first_id},
    )
    assert rollback.status_code == 200
    assert rollback.json()["rollback_from_version_id"] == active_id
    new_id = rollback.json()["id"]
    with get_db_connection() as conn:
        old = conn.execute("SELECT content FROM prompt_versions WHERE id = ?", (active_id,)).fetchone()[0]
        clone = conn.execute("SELECT content, status FROM prompt_versions WHERE id = ?", (new_id,)).fetchone()
        event = conn.execute(
            "SELECT source_version_id, previous_active_version_id, new_version_id "
            "FROM prompt_version_audit_events WHERE action = 'rollback' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert clone["content"] == old
    assert clone["status"] == "active"
    assert tuple(event) == (active_id, first_id, new_id)


def test_render_and_preview_use_selected_prompt_versions_and_require_admin(client):
    _episode()
    assert client.get("/admin/prompts").status_code == 200
    assert client.get("/admin/prompts", headers={}).status_code == 200  # session cookie remains valid
    template_key = "generate_narrative_arc"
    program_prompt = client.post("/admin/prompts", json={"template_key": template_key, "program_id": "radio-test"})
    assert program_prompt.status_code == 201
    prompt_id = program_prompt.json()["id"]
    draft = client.post(f"/admin/prompts/{prompt_id}/versions", json={"content": "program {summaries_json}"})
    common_template_id = _template_id(template_key)
    with get_db_connection() as conn:
        common_id = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (common_template_id,)
        ).fetchone()[0]
    common_preview = client.post(
        "/admin/programs/radio-test/preview-prompt",
        json={"template_key": template_key, "episode_id": 71},
    )
    assert common_preview.status_code == 200
    assert common_preview.json()["version_id"] == common_id
    activated = client.post(
        f"/admin/prompts/versions/{draft.json()['id']}/activate",
        json={"change_note": "program prompt", "expected_active_version_id": None},
    )
    assert activated.status_code == 200
    preview = client.post(
        "/admin/programs/radio-test/preview-prompt",
        json={"template_key": template_key, "episode_id": 71},
    )
    assert preview.status_code == 200
    assert preview.json()["version_id"] == draft.json()["id"]
    assert "Test article" in preview.json()["prompt"]
    rendered = client.post(
        f"/admin/prompts/versions/{common_id}/render", json={"episode_id": 71}
    )
    assert rendered.status_code == 200
    assert rendered.json()["version_id"] == common_id

    # テンプレート変数が要約だけで構成されない場合、不完全なプロンプトを成功応答しない。
    category_version_id = client.get(f"/admin/prompts/{_template_id('category')}/versions").json()["versions"][0]["id"]
    assert client.post(
        f"/admin/prompts/versions/{category_version_id}/render", json={"episode_id": 71}
    ).status_code == 422
    assert client.post(
        "/admin/programs/radio-test/preview-prompt",
        json={"template_key": "category", "episode_id": 71},
    ).status_code == 422
    radio_template_id = _template_id("generate_radio_script")
    radio_version_id = client.get(f"/admin/prompts/{radio_template_id}/versions").json()["versions"][0]["id"]
    assert client.post(
        f"/admin/prompts/versions/{radio_version_id}/render", json={"episode_id": 71}
    ).status_code == 422

    from fastapi.testclient import TestClient
    from app.main import app
    unauthenticated = TestClient(app)
    assert unauthenticated.get("/admin/prompts").status_code == 401
    assert unauthenticated.post("/admin/prompts", json={"template_key": "category"}).status_code == 401
    assert unauthenticated.get("/admin/prompts/1/versions").status_code == 401
    assert unauthenticated.post("/admin/prompts/1/versions", json={"content": "x"}).status_code == 401
    assert unauthenticated.post(
        "/admin/prompts/versions/1/activate",
        json={"change_note": "x", "expected_active_version_id": None},
    ).status_code == 401
    assert unauthenticated.post(
        "/admin/prompts/versions/1/rollback",
        json={"change_note": "x", "expected_active_version_id": None},
    ).status_code == 401
    assert unauthenticated.post("/admin/prompts/versions/1/render", json={"episode_id": 1}).status_code == 401
    assert unauthenticated.post(
        "/admin/programs/radio-test/preview-prompt",
        json={"template_key": "category", "episode_id": 1},
    ).status_code == 401
