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


def _episode(episode_id=71, program_id="radio-test", kind="radio"):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO programs(id, name, kind, definition) VALUES (?, ?, ?, '{}')",
            (program_id, "Test Radio", kind),
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
    with get_db_connection() as conn:
        preview_audit_count = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE operation = 'admin_prompt_preview' AND result = 'success'"
        ).fetchone()[0]
    assert client.post(
        "/admin/programs/radio-test/preview-prompt",
        json={"template_key": "category", "episode_id": 71},
    ).status_code == 422
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE operation = 'admin_prompt_preview' AND result = 'success'"
        ).fetchone()[0] == preview_audit_count
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


def test_preview_renders_saved_generation_context_for_target_templates(client):
    _episode(episode_id=72, program_id="preview-test")
    from app.api import admin_prompts
    episode_dir = admin_prompts.EPISODES_DIR / "72"
    with get_db_connection() as conn:
        article_id = conn.execute(
            "INSERT INTO articles(title, source, url, text, summary, category, importance_score, difficulty, status, published_at) "
            "VALUES ('記事タイトル', '媒体', 'https://example.test/a', '本文' || printf('%0200d', 1), '要約本文', 'technology', 5, 2, 'summarized', '2026-09-01')",
        ).lastrowid
        conn.execute(
            "INSERT INTO episode_items(episode_id, article_id, item_order, segment_text) VALUES (72, ?, 1, '台本本文')",
            (article_id,),
        )
    (episode_dir / "article_input.json").write_text(json.dumps({
        "id": article_id, "title": "記事タイトル", "source": "媒体",
        "url": "https://example.test/a", "text": "本文" + "1" * 200,
        "published_at": "2026-09-01",
    }, ensure_ascii=False), encoding="utf-8")
    (episode_dir / "summaries.json").write_text(json.dumps([
        {"article_id": article_id, "title": "記事タイトル", "summary": "要約本文",
         "category": "technology", "importance_score": 5, "difficulty": 2},
    ], ensure_ascii=False), encoding="utf-8")
    (episode_dir / "script.json").write_text(json.dumps({
        "style": "solo", "mc_gender": "female", "discussion_article_id": article_id,
        "lines": [{"article_id": article_id, "text": "最終版本文", "section": "news"}],
    }, ensure_ascii=False), encoding="utf-8")
    review_dir = episode_dir / "review"
    review_dir.mkdir()
    (review_dir / "original_script.json").write_text(json.dumps({
        "style": "solo", "mc_gender": "female", "discussion_article_id": article_id,
        "lines": [{"article_id": article_id, "text": "レビュー前の原稿", "section": "news"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (episode_dir / "prompt_context.json").write_text(json.dumps({
            "summaries_json": json.dumps([{"id": article_id, "title": "記事タイトル", "source": "媒体",
                                            "url": "https://example.test/a", "summary": "要約本文",
                                            "category": "technology", "importance_score": 5, "difficulty": 2}], ensure_ascii=False, indent=2),
            "narrative_arc_section": "# 保存済み Narrative Arc\n",
    }, ensure_ascii=False), encoding="utf-8")
    (review_dir / "review.json").write_text(json.dumps({"reviews": {
        "beginner": {"score": 1}, "genius": {"score": 2}, "worried": {"score": 3},
        "positive": {"score": 4}, "radio": {"score": 5},
    }}, ensure_ascii=False), encoding="utf-8")

    review_templates = ("review_beginner_director", "review_genius_director", "review_positive_director",
                        "review_radio_director", "review_worried_director", "review_synthesize")
    for template_key in ("generate_radio_script", "generate_commentary_script", *review_templates,
                         "category", "summarize_article"):
        template_id = _template_id(template_key)
        with get_db_connection() as conn:
            version_id = conn.execute(
                "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
            ).fetchone()[0]
        rendered = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 72})
        assert rendered.status_code == 200, (template_key, rendered.text)
        assert rendered.json()["prompt"]
        previewed = client.post("/admin/programs/preview-test/preview-prompt", json={
            "episode_id": 72, "template_key": template_key,
        })
        assert previewed.status_code == 200, (template_key, previewed.text)
        if template_key == "generate_radio_script":
            assert rendered.json()["prompt"] == previewed.json()["prompt"]
            assert "# 保存済み Narrative Arc" in rendered.json()["prompt"]
            assert "記事タイトル" in rendered.json()["prompt"]
        elif template_key == "generate_commentary_script":
            assert "記事タイトル" in rendered.json()["prompt"]
            assert "本文" in rendered.json()["prompt"]
            assert rendered.json()["prompt"] == previewed.json()["prompt"]
        elif template_key == "category":
            assert "最終版本文" in rendered.json()["prompt"]
        elif template_key in review_templates:
            assert "レビュー前の原稿" in rendered.json()["prompt"]
            assert "最終版本文" not in rendered.json()["prompt"]
        if template_key == "review_synthesize":
            assert '"score": 1' in rendered.json()["prompt"]


def test_commentary_review_uses_source_article_for_all_review_templates(client):
    _episode(episode_id=74, program_id="commentary-review-test", kind="commentary")
    from app.api import admin_prompts
    episode_dir = admin_prompts.EPISODES_DIR / "74"
    (episode_dir / "summaries.json").unlink()
    with get_db_connection() as conn:
        article_id = conn.execute(
            "INSERT INTO articles(title, source, url, text, published_at, summary, category, importance_score, difficulty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("STALE DB title", "STALE DB source", "https://example.test/commentary", "STALE DB body",
             "2020-01-01", "STALE DB summary", "stale-category", 1, 9),
        ).lastrowid
    article_input = {
        "id": article_id, "title": "Fetched commentary title", "source": "Fetched publisher",
        "url": "https://example.test/commentary", "text": "Freshly fetched article body",
        "published_at": "2026-09-02",
    }
    (episode_dir / "article_input.json").write_text(
        json.dumps(article_input, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    commentary_script = {
        "style": "dialogue", "mc_gender": "male",
        "lines": [{"article_id": article_id, "text": "commentary final script"}],
    }
    review_dir = episode_dir / "review"
    review_dir.mkdir()
    (episode_dir / "script.json").write_text(json.dumps(commentary_script), encoding="utf-8")
    (review_dir / "original_script.json").write_text(json.dumps({
        **commentary_script, "lines": [{"article_id": article_id, "text": "commentary original script"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (review_dir / "review.json").write_text(json.dumps({"reviews": {
        "beginner": {}, "genius": {}, "worried": {}, "positive": {}, "radio": {},
    }}), encoding="utf-8")

    templates = ("review_beginner_director", "review_genius_director", "review_positive_director",
                 "review_radio_director", "review_worried_director", "review_synthesize")
    for template_key in templates:
        template_id = _template_id(template_key)
        with get_db_connection() as conn:
            version_id = conn.execute(
                "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
            ).fetchone()[0]
        rendered = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 74})
        assert rendered.status_code == 200, (template_key, rendered.text)
        prompt = rendered.json()["prompt"]
        assert "Fetched commentary title" in prompt
        assert "Freshly fetched article body" in prompt
        assert "STALE DB title" not in prompt
        assert "STALE DB body" not in prompt
        assert "STALE DB summary" not in prompt
        assert "stale-category" not in prompt
        assert "commentary original script" in prompt
        assert "commentary final script" not in prompt
        if template_key.startswith("review_"):
            for field, value in article_input.items():
                assert f'"{field}": {json.dumps(value, ensure_ascii=False)}' in prompt
        preview = client.post("/admin/programs/commentary-review-test/preview-prompt", json={
            "template_key": template_key, "episode_id": 74,
        })
        assert preview.status_code == 200, (template_key, preview.text)
        assert preview.json()["prompt"] == prompt

    template_key = "generate_commentary_script"
    template_id = _template_id(template_key)
    with get_db_connection() as conn:
        version_id = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
        ).fetchone()[0]
    rendered = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 74})
    preview = client.post("/admin/programs/commentary-review-test/preview-prompt", json={
        "template_key": template_key, "episode_id": 74,
    })
    assert rendered.status_code == preview.status_code == 200
    assert rendered.json()["prompt"] == preview.json()["prompt"]
    for value in ("Fetched commentary title", "Freshly fetched article body"):
        assert value in rendered.json()["prompt"]
    assert "STALE DB" not in rendered.json()["prompt"]


def test_old_commentary_without_saved_article_input_is_rejected(client):
    _episode(episode_id=77, program_id="old-commentary-test", kind="commentary")
    from app.api import admin_prompts
    episode_dir = admin_prompts.EPISODES_DIR / "77"
    (episode_dir / "summaries.json").unlink()
    with get_db_connection() as conn:
        article_id = conn.execute(
            "INSERT INTO articles(title, source, url, text) VALUES (?, ?, ?, ?)",
            ("Only DB article", "Old source", "https://example.test/old-commentary", "Only DB body"),
        ).lastrowid
    (episode_dir / "script.json").write_text(json.dumps({
        "style": "solo", "mc_gender": "female",
        "lines": [{"article_id": article_id, "text": "old commentary"}],
    }), encoding="utf-8")
    review_dir = episode_dir / "review"
    review_dir.mkdir()
    (review_dir / "original_script.json").write_text(json.dumps({
        "style": "solo", "mc_gender": "female",
        "lines": [{"article_id": article_id, "text": "old commentary"}],
    }), encoding="utf-8")
    (review_dir / "review.json").write_text(json.dumps({"reviews": {
        "beginner": {}, "genius": {}, "worried": {}, "positive": {}, "radio": {},
    }}), encoding="utf-8")

    for template_key in ("generate_commentary_script", "review_synthesize"):
        template_id = _template_id(template_key)
        with get_db_connection() as conn:
            version_id = conn.execute(
                "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
            ).fetchone()[0]
        render = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 77})
        preview = client.post("/admin/programs/old-commentary-test/preview-prompt", json={
            "template_key": template_key, "episode_id": 77,
        })
        assert render.status_code == 422, (template_key, render.text)
        assert preview.status_code == 422, (template_key, preview.text)
        assert "article_input.json" in render.json()["detail"]


def test_prompt_preview_reports_missing_required_inputs(client):
    _episode(episode_id=73, program_id="missing-preview-test")
    from app.api import admin_prompts
    (admin_prompts.EPISODES_DIR / "73" / "summaries.json").write_text("[]", encoding="utf-8")
    template_id = _template_id("generate_radio_script")
    with get_db_connection() as conn:
        version_id = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
        ).fetchone()[0]
    response = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 73})
    assert response.status_code == 422
    assert "summaries_json" in response.json()["detail"]
    preview = client.post("/admin/programs/missing-preview-test/preview-prompt", json={
        "template_key": "generate_radio_script", "episode_id": 73,
    })
    assert preview.status_code == 422
    assert "summaries_json" in preview.json()["detail"]


def test_prompt_preview_rejects_missing_review_category_and_article_inputs(client):
    _episode(episode_id=75, program_id="incomplete-preview-test")
    from app.api import admin_prompts
    episode_dir = admin_prompts.EPISODES_DIR / "75"
    (episode_dir / "summaries.json").write_text("[]", encoding="utf-8")
    (episode_dir / "script.json").write_text(json.dumps({"lines": []}), encoding="utf-8")
    review_dir = episode_dir / "review"
    review_dir.mkdir()
    (review_dir / "original_script.json").write_text(json.dumps({"lines": []}), encoding="utf-8")
    (review_dir / "review.json").write_text(json.dumps({"reviews": {
        "beginner": {}, "genius": {}, "worried": {}, "positive": {},
    }}), encoding="utf-8")
    with get_db_connection() as conn:
        evidence_article_id = conn.execute(
            "INSERT INTO articles(title, source, url, text, published_at) VALUES (?, ?, ?, ?, ?)",
            ("Evidence article", "Source", "https://example.test/evidence", "Evidence text", "2026-09-03"),
        ).lastrowid
    (review_dir / "original_script.json").write_text(json.dumps({
        "lines": [{"article_id": evidence_article_id, "text": "review source"}],
    }), encoding="utf-8")
    (episode_dir / "article_input.json").write_text(json.dumps({
        "id": evidence_article_id, "title": "Evidence article", "source": "Source",
        "url": "https://example.test/evidence", "text": "Evidence text", "published_at": "2026-09-03",
    }), encoding="utf-8")
    for template_key in ("review_synthesize", "category"):
        template_id = _template_id(template_key)
        with get_db_connection() as conn:
            version_id = conn.execute(
                "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (template_id,),
            ).fetchone()[0]
        render = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 75})
        preview = client.post("/admin/programs/incomplete-preview-test/preview-prompt", json={
            "template_key": template_key, "episode_id": 75,
        })
        assert render.status_code == 422, (template_key, render.text)
        assert preview.status_code == 422, (template_key, preview.text)
    synth_id = _template_id("review_synthesize")
    with get_db_connection() as conn:
        synth_version = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (synth_id,),
        ).fetchone()[0]
    missing_review = client.post(f"/admin/prompts/versions/{synth_version}/render", json={"episode_id": 75})
    assert "reviews.radio" in missing_review.json()["detail"]
    missing_category = client.post("/admin/programs/incomplete-preview-test/preview-prompt", json={
        "template_key": "category", "episode_id": 75,
    })
    assert "source" in missing_category.json()["detail"]

    with get_db_connection() as conn:
        article_id = conn.execute(
            "INSERT INTO articles(title, source, url, text, published_at) VALUES (?, NULL, NULL, '', NULL)",
            ("Article without required fields",),
        ).lastrowid
    (episode_dir / "summaries.json").write_text(json.dumps([{"article_id": article_id}]), encoding="utf-8")
    summarize_id = _template_id("summarize_article")
    with get_db_connection() as conn:
        summarize_version = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (summarize_id,),
        ).fetchone()[0]
    missing_article = client.post(f"/admin/prompts/versions/{summarize_version}/render", json={"episode_id": 75})
    assert missing_article.status_code == 422
    assert all(key in missing_article.json()["detail"] for key in ("published_at", "source", "text", "url"))
    missing_article_preview = client.post("/admin/programs/incomplete-preview-test/preview-prompt", json={
        "template_key": "summarize_article", "episode_id": 75,
    })
    assert missing_article_preview.status_code == 422
    assert all(key in missing_article_preview.json()["detail"] for key in ("published_at", "source", "text", "url"))


def test_review_preview_rejects_when_original_script_is_not_saved(client):
    _episode(episode_id=76, program_id="no-original-preview-test")
    from app.api import admin_prompts
    episode_dir = admin_prompts.EPISODES_DIR / "76"
    (episode_dir / "script.json").write_text(json.dumps({"lines": [{"article_id": 1, "text": "final"}]}), encoding="utf-8")
    review_dir = episode_dir / "review"
    review_dir.mkdir()
    (review_dir / "review.json").write_text(json.dumps({"reviews": {
        "beginner": {}, "genius": {}, "worried": {}, "positive": {}, "radio": {},
    }}), encoding="utf-8")
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO script_revisions(episode_id, revision, script_json, source) VALUES (76, 1, ?, 'reviewed')",
            (json.dumps({"lines": [{"article_id": 1, "text": "final"}]}),),
        )
    version_id = _template_id("review_synthesize")
    with get_db_connection() as conn:
        version_id = conn.execute(
            "SELECT id FROM prompt_versions WHERE template_id = ? AND status = 'active'", (version_id,),
        ).fetchone()[0]
    response = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 76})
    assert response.status_code == 422
    assert "original pre-review script" in response.json()["detail"]
    preview = client.post("/admin/programs/no-original-preview-test/preview-prompt", json={
        "template_key": "review_synthesize", "episode_id": 76,
    })
    assert preview.status_code == 422
    assert "original pre-review script" in preview.json()["detail"]
