import json

from app.db.connection import get_db_connection


def _profile():
    return {
        "id": "custom-radio",
        "name": "ニュースのとなり",
        "kind": "radio",
        "cast": [{"key": "host", "name": "司会", "role": "MC"}],
        "segments": [
            {"id": "intro", "kind": "intro", "order": 0, "min_lines": 1,
             "max_lines": 2, "speaker_keys": ["host"]}
        ],
        "options": {"style": None, "mc_gender": None, "narrative_arc": False,
                    "review_mode": "on_failure"},
    }


def _create_test_program(client):
    profile = _profile()
    assert client.post("/admin/programs", json={**profile, "is_active": True}).status_code == 201
    return profile["id"]


def _draft_script_prompt_id(program_id):
    from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS

    definition = PROMPT_TEMPLATE_DEFINITIONS["generate_radio_script"]
    with get_db_connection() as conn:
        template_id = conn.execute(
            "INSERT INTO prompt_templates(template_key, program_id, required_variables, allowed_variables) "
            "VALUES (?, ?, ?, ?)",
            ("generate_radio_script", program_id, json.dumps(definition["required_variables"]),
             json.dumps(definition["allowed_variables"])),
        ).lastrowid
        return conn.execute(
            "INSERT INTO prompt_versions(template_id, version, content, status) VALUES (?, 1, ?, 'draft')",
            (template_id, "Draft instruction {narrative_arc_section} {summaries_json}"),
        ).lastrowid


def _queued_payload(dry_run_id):
    with get_db_connection() as conn:
        row = conn.execute("SELECT payload FROM generation_jobs WHERE id=?", (dry_run_id,)).fetchone()
    return json.loads(row["payload"])


def test_dry_run_is_queued_and_retrievable(client, monkeypatch):
    from app.api import admin_dry_runs

    monkeypatch.setattr(admin_dry_runs, "dispatch_job", lambda _job_id: None)
    program_id = _create_test_program(client)
    response = client.post(
        f"/admin/programs/{program_id}/dry-run",
        json={},
        headers={"Idempotency-Key": "dry-run-queued-test"},
    )
    assert response.status_code == 202
    result_id = response.json()["id"]
    assert response.json()["status"] in {"running", "queued"}
    detail = client.get(f"/admin/dry-runs/{result_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == result_id
    assert detail.json()["status"] == response.json()["status"]
    queued = client.get("/admin/dry-runs?status=queued")
    assert queued.status_code == 200
    assert any(row["id"] == result_id for row in queued.json()) == (response.json()["status"] == "queued")


def test_dry_run_past_episode_requires_valid_summaries(client):
    program_id = _create_test_program(client)
    response = client.post(
        f"/admin/programs/{program_id}/dry-run",
        json={"input_episode_id": 99999},
        headers={"Idempotency-Key": "dry-run-missing-input-test"},
    )
    assert response.status_code == 422
    assert "summaries.json" in response.json()["detail"]


def test_dry_run_script_does_not_mark_articles_used(client, monkeypatch):
    from app.api import admin_dry_runs

    fake_profile = _profile()
    monkeypatch.setattr(admin_dry_runs, "_get_input_summaries", lambda *_: [{"id": 41, "summary": "summary"}])
    monkeypatch.setattr(admin_dry_runs, "dispatch_job", lambda _job_id: None)
    program_id = _create_test_program(client)
    created = client.post(
        f"/admin/programs/{program_id}/dry-run",
        json={},
        headers={"Idempotency-Key": "dry-run-output-test"},
    )
    dry_run_id = created.json()["id"]
    from app.batch import generate_script as module

    def fake_generate(path, **kwargs):
        assert kwargs["mark_articles"] is False
        with open(path, "w", encoding="utf-8") as script_file:
            json.dump({"lines": [{"text": "line"}]}, script_file)

    monkeypatch.setattr(module, "generate_script", fake_generate)
    from app.batch import final_validation
    monkeypatch.setattr(final_validation, "validate_final_script_file", lambda *_args, **_kwargs: {
        "critical_issues": [], "warnings": [],
    })
    with get_db_connection() as conn:
        conn.execute("UPDATE dry_runs SET status='queued' WHERE id=?", (dry_run_id,))
    assert admin_dry_runs.execute_dry_run(dry_run_id, {
        "program_id": program_id,
        "current_definition": fake_profile,
    }) is True
    result = client.get(f"/admin/dry-runs/{dry_run_id}").json()
    assert result["status"] == "completed"
    assert "current" in result["script_json"]


def test_dry_run_comparison_returns_both_scripts_and_checks(client, monkeypatch):
    from app.api import admin_dry_runs
    from app.batch import final_validation

    monkeypatch.setattr(admin_dry_runs, "_get_input_summaries", lambda *_: [{"id": 41, "summary": "same"}])
    monkeypatch.setattr(admin_dry_runs, "dispatch_job", lambda _job_id: None)
    program_id = _create_test_program(client)
    prompt_id = _draft_script_prompt_id(program_id)
    response = client.post(
        f"/admin/programs/{program_id}/dry-run",
        json={"draft_program_definition": _profile(), "draft_prompt_version_id": prompt_id},
        headers={"Idempotency-Key": "dry-run-comparison-test"},
    )
    dry_run_id = response.json()["id"]

    from app.batch import generate_script as module

    def fake_generate(path, **kwargs):
        title = "draft" if kwargs.get("prompt_version_id") == prompt_id else "current"
        with open(path, "w", encoding="utf-8") as script_file:
            json.dump({"title": title, "lines": [{"text": title}]}, script_file)

    monkeypatch.setattr(module, "generate_script", fake_generate)
    monkeypatch.setattr(final_validation, "validate_final_script_file", lambda *_args, **_kwargs: {
        "critical_issues": [{"code": "SCRIPT_CHECK", "message": "error", "line_indices": [0]}],
        "warnings": [{"code": "SCRIPT_WARNING", "message": "warning", "line_indices": [0]}],
    })

    assert admin_dry_runs.execute_dry_run(dry_run_id, _queued_payload(dry_run_id)) is True
    result = client.get(f"/admin/dry-runs/{dry_run_id}").json()
    assert result["status"] == "completed"
    assert result["script_json"]["current"]["title"] == "current"
    assert result["script_json"]["draft"]["title"] == "draft"
    for checks in result["validation_json"].values():
        assert [(check["code"], check["severity"], check["line_indices"]) for check in checks] == [
            ("SCRIPT_CHECK", "error", [0]), ("SCRIPT_WARNING", "warning", [0]),
        ]
    completed = client.get("/admin/dry-runs?status=completed").json()
    queued = client.get("/admin/dry-runs?status=queued").json()
    assert any(row["id"] == dry_run_id for row in completed)
    assert all(row["id"] != dry_run_id for row in queued)


def test_dry_run_failure_state_is_persisted(client, monkeypatch):
    from app.api import admin_dry_runs

    monkeypatch.setattr(admin_dry_runs, "dispatch_job", lambda _job_id: None)
    monkeypatch.setattr(
        admin_dry_runs, "_get_input_summaries",
        lambda *_: (_ for _ in ()).throw(ValueError("test input failure")),
    )
    program_id = _create_test_program(client)
    response = client.post(
        f"/admin/programs/{program_id}/dry-run",
        json={},
        headers={"Idempotency-Key": "dry-run-failure-test"},
    )
    dry_run_id = response.json()["id"]
    assert admin_dry_runs.execute_dry_run(dry_run_id, _queued_payload(dry_run_id)) is False
    result = client.get(f"/admin/dry-runs/{dry_run_id}").json()
    assert result["status"] == "failed"
    assert result["error"] == "test input failure"
