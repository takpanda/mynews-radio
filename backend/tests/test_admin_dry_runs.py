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
    assert client.get("/admin/dry-runs?status=queued").status_code == 200


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
    monkeypatch.setattr(module, "generate_script", lambda path, **kwargs: open(path, "w").write(
        json.dumps({"lines": [{"text": "line"}]})
    ))
    monkeypatch.setattr(module, "lint_script", lambda *_args, **_kwargs: [])
    with get_db_connection() as conn:
        conn.execute("UPDATE dry_runs SET status='queued' WHERE id=?", (dry_run_id,))
    assert admin_dry_runs.execute_dry_run(dry_run_id, {
        "program_id": program_id,
        "current_definition": fake_profile,
    }) is True
    result = client.get(f"/admin/dry-runs/{dry_run_id}").json()
    assert result["status"] == "completed"
    assert "current" in result["script_json"]
