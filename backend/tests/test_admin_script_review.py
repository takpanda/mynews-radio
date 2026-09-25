import json
import sqlite3
from pathlib import Path
from unittest.mock import patch


def _episode_with_script(status="awaiting_review"):
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-08-01", status=status)
    script = {"style": "solo", "lines": [{"section": "intro", "text": "放送を始めます", "speaker": "male"}]}
    script_path = Path(__import__("os").environ["EPISODES_DIR"]) / str(episode_id) / "script.json"
    script_path.parent.mkdir(parents=True)
    script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET review_mode='on_failure' WHERE id=?", (episode_id,))
    return episode_id, script


def test_script_edit_uses_revision_compare_and_swap_and_audit(client):
    from app.db.connection import get_db_connection

    episode_id, script = _episode_with_script()
    first = client.get(f"/admin/episodes/{episode_id}/script")
    assert first.status_code == 200
    assert first.json()["revision"] == 1

    changed = {**script, "title": "修正版"}
    saved = client.put(f"/admin/episodes/{episode_id}/script", json={"revision": 1, "script": changed})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2

    conflict = client.put(f"/admin/episodes/{episode_id}/script", json={"revision": 1, "script": script})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["latest_revision"] == 2

    with get_db_connection() as conn:
        revisions = conn.execute("SELECT revision, source FROM script_revisions WHERE episode_id=? ORDER BY revision", (episode_id,)).fetchall()
        audits = conn.execute("SELECT operation FROM audit_logs WHERE episode_id=?", (episode_id,)).fetchall()
    assert [(row["revision"], row["source"]) for row in revisions] == [(1, "generated"), (2, "human")]
    assert any(row["operation"] == "script_update" for row in audits)


def test_approve_is_idempotent_and_registers_one_audio_job(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with patch("app.api.admin_script_review._validate_episode_script", return_value={"can_approve": True, "results": []}), \
         patch("app.api.admin_script_review.dispatch_job") as dispatch:
        first = client.post(f"/admin/episodes/{episode_id}/approve")
        second = client.post(f"/admin/episodes/{episode_id}/approve")

    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    dispatch.assert_called_once()
    with get_db_connection() as conn:
        jobs = conn.execute("SELECT operation FROM generation_jobs WHERE episode_id=?", (episode_id,)).fetchall()
        status = conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()["status"]
    assert [row["operation"] for row in jobs] == ["synthesize"]
    assert status == "synthesizing"


def test_approve_rejects_remaining_validation_errors(client):
    episode_id, _ = _episode_with_script()
    with patch("app.api.admin_script_review._validate_episode_script", return_value={"can_approve": False, "results": [{"code": "BAD", "message": "NG", "line_indices": [], "severity": "error"}]}):
        response = client.post(f"/admin/episodes/{episode_id}/approve")
    assert response.status_code == 409


def test_reject_discard_transitions_only_awaiting_review_episode(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "discard"})
    assert response.status_code == 200
    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()["status"] == "discarded"
    assert client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "discard"}).status_code == 409


def test_preview_audio_enforces_admin_per_minute_quota(client):
    episode_id, _ = _episode_with_script()

    def write_fake_audio(self, text, speaker, output_path, **kwargs):
        Path(output_path).write_bytes(b"RIFF-preview")
        return True

    with patch("app.services.voicevox_client.VoicevoxClient.synthesize_line", write_fake_audio):
        responses = [client.post(f"/admin/episodes/{episode_id}/lines/0/preview-audio") for _ in range(5)]
        limited = client.post(f"/admin/episodes/{episode_id}/lines/0/preview-audio")

    assert all(response.status_code == 200 for response in responses)
    assert limited.status_code == 429


def test_script_revision_migration_keeps_existing_episode_states():
    from app.db.migration import migrate_script_revisions

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE episodes(id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    conn.executemany("INSERT INTO episodes(id, status) VALUES (?, ?)", [(1, "generating"), (2, "failed")])

    assert migrate_script_revisions(conn) is True
    rows = conn.execute("SELECT id, status, review_mode FROM episodes ORDER BY id").fetchall()
    assert [(row["status"], row["review_mode"]) for row in rows] == [
        ("generating", "on_failure"),
        ("failed", "on_failure"),
    ]
    conn.close()
