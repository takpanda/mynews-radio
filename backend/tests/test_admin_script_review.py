import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


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


def test_get_script_returns_snapshot_cast_in_order_and_keeps_snapshot_names(client):
    from app.db.connection import get_db_connection

    episode_id, script = _episode_with_script()
    snapshot_cast = [
        {"key": "host_a", "name": "保存時の名前 A", "role": "進行", "mc_id": "mc-a"},
        {"key": "host_b", "name": "保存時の名前 B", "role": "解説", "mc_id": "mc-b"},
    ]
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO mc_profiles(id, name, role) VALUES ('mc-a', '現在の名前 A', '現在の役割 A'), ('mc-b', '現在の名前 B', '現在の役割 B')"
        )
        conn.execute(
            "UPDATE episodes SET program_snapshot=? WHERE id=?",
            (json.dumps({"name": "番組名", "cast": snapshot_cast}, ensure_ascii=False), episode_id),
        )

    response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert {key: response.json()[key] for key in ("episode_id", "revision", "script", "cast")} == {
        "episode_id": episode_id,
        "revision": 1,
        "script": script,
        "cast": [
            {"key": "host_a", "name": "保存時の名前 A", "role": "進行"},
            {"key": "host_b", "name": "保存時の名前 B", "role": "解説"},
        ],
    }
    assert response.json()["validation"]["source"] == "current"
    assert response.json()["validation"]["revision"] == 1


def test_get_script_returns_null_cast_for_episode_without_snapshot(client):
    episode_id, script = _episode_with_script()

    response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert {key: response.json()[key] for key in ("episode_id", "revision", "script", "cast")} == {
        "episode_id": episode_id,
        "revision": 1,
        "script": script,
        "cast": None,
    }
    assert response.json()["validation"]["source"] == "current"
    assert response.json()["validation"]["revision"] == 1


def test_get_script_uses_generated_final_validation_for_revision_one(client):
    episode_id, script = _episode_with_script()
    report = {
        "critical_issues": [{"code": "BLOCKED", "message": "要確認", "line_indices": [0]}],
        "warnings": [{"code": "CAUTION", "message": "注意", "line_indices": []}],
    }
    report_path = Path(__import__("os").environ["EPISODES_DIR"]) / str(episode_id) / "final_validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    with patch("app.api.admin_script_review._validate_episode_script") as validate:
        response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert response.json()["script"] == script
    assert response.json()["validation"] == {
        "can_approve": False,
        "results": [
            {"code": "BLOCKED", "message": "要確認", "line_indices": [0], "severity": "error"},
            {"code": "CAUTION", "message": "注意", "line_indices": [], "severity": "warning"},
        ],
        "source": "generated",
        "revision": 1,
    }
    validate.assert_not_called()


@pytest.mark.parametrize("report_contents", [None, "{invalid json"])
def test_get_script_revalidates_when_generated_final_validation_is_missing_or_corrupt(client, report_contents):
    episode_id, script = _episode_with_script()
    report_path = Path(__import__("os").environ["EPISODES_DIR"]) / str(episode_id) / "final_validation.json"
    if report_contents is not None:
        report_path.write_text(report_contents, encoding="utf-8")
    current = {"can_approve": False, "results": [{"code": "CURRENT", "severity": "error"}]}

    with patch("app.api.admin_script_review._validate_episode_script", return_value=current) as validate:
        response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert response.json()["script"] == script
    assert response.json()["validation"] == {**current, "source": "current", "revision": 1}
    validate.assert_called_once_with(episode_id, script)


@pytest.mark.parametrize(
    "finding",
    [
        {"code": "X"},
        {"code": "X", "message": "破損", "line_indices": ["0"]},
        {"code": "X", "message": 123, "line_indices": [0]},
    ],
)
def test_get_script_revalidates_when_generated_finding_schema_is_invalid(client, finding):
    episode_id, script = _episode_with_script()
    report_path = Path(__import__("os").environ["EPISODES_DIR"]) / str(episode_id) / "final_validation.json"
    report_path.write_text(
        json.dumps({"critical_issues": [finding], "warnings": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    current = {"can_approve": True, "results": []}

    with patch("app.api.admin_script_review._validate_episode_script", return_value=current) as validate:
        response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert response.json()["validation"] == {**current, "source": "current", "revision": 1}
    validate.assert_called_once_with(episode_id, script)


def test_get_script_revalidates_human_revision_even_when_generated_report_exists(client):
    from app.db.connection import get_db_connection

    episode_id, script = _episode_with_script()
    report_path = Path(__import__("os").environ["EPISODES_DIR"]) / str(episode_id) / "final_validation.json"
    report_path.write_text(json.dumps({"critical_issues": [], "warnings": []}), encoding="utf-8")
    edited_script = {**script, "title": "手編集"}
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO script_revisions(episode_id, revision, script_json, source) VALUES (?, 2, ?, 'human')",
            (episode_id, json.dumps(edited_script, ensure_ascii=False)),
        )
    current = {"can_approve": True, "results": []}

    with patch("app.api.admin_script_review._validate_episode_script", return_value=current) as validate:
        response = client.get(f"/admin/episodes/{episode_id}/script")

    assert response.status_code == 200
    assert response.json()["script"] == edited_script
    assert response.json()["validation"] == {**current, "source": "current", "revision": 2}
    validate.assert_called_once_with(episode_id, edited_script)


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


@pytest.mark.parametrize("body", [None, {"force": False}])
def test_approve_rejects_remaining_validation_errors(client, body):
    episode_id, _ = _episode_with_script()
    with patch("app.api.admin_script_review._validate_episode_script", return_value={"can_approve": False, "results": [{"code": "BAD", "message": "NG", "line_indices": [], "severity": "error"}]}):
        response = client.post(f"/admin/episodes/{episode_id}/approve", json=body) if body is not None else client.post(f"/admin/episodes/{episode_id}/approve")
    assert response.status_code == 409
    assert response.json()["detail"]["results"][0]["code"] == "BAD"


def test_approve_force_bypasses_validation_and_is_audited(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    invalid = {"can_approve": False, "results": [{"code": "BAD", "message": "NG", "line_indices": [], "severity": "error"}]}
    with patch("app.api.admin_script_review._validate_episode_script", return_value=invalid), \
         patch("app.api.admin_script_review.dispatch_job") as dispatch, \
         patch("app.api.admin_script_review._audit", wraps=__import__("app.api.admin_script_review", fromlist=["_audit"])._audit) as audit:
        response = client.post(f"/admin/episodes/{episode_id}/approve", json={"force": True})

    assert response.status_code == 200
    assert response.json()["status"] == "synthesizing"
    dispatch.assert_called_once_with(response.json()["job_id"])
    audit.assert_called_once()
    assert audit.call_args.args[1] == "script_force_approve"
    assert audit.call_args.args[4] == {"revision": 1, "force": True}
    with get_db_connection() as conn:
        jobs = conn.execute("SELECT operation FROM generation_jobs WHERE episode_id=?", (episode_id,)).fetchall()
        status = conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()["status"]
        audits = conn.execute("SELECT operation FROM audit_logs WHERE episode_id=?", (episode_id,)).fetchall()
    assert [row["operation"] for row in jobs] == ["synthesize"]
    assert status == "synthesizing"
    assert [row["operation"] for row in audits].count("script_force_approve") == 1


def test_reject_discard_transitions_only_awaiting_review_episode(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "discard"})
    assert response.status_code == 200
    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()["status"] == "discarded"
    assert client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "discard"}).status_code == 409


def test_reject_regenerate_keeps_episode_and_registers_generation_job(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET program_id='radio_news_neighbor' WHERE id=?", (episode_id,))
        owner_id = conn.execute(
            "SELECT admin_user_id FROM sessions WHERE token=?",
            (next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"),),
        ).fetchone()["admin_user_id"]
        conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, client_ip_hash, episode_id, payload, status) "
            "VALUES (?, 'daily', ?, 'source-hash', 'source-ip', ?, ?, 'completed')",
            (owner_id, f"source-{episode_id}", episode_id, json.dumps({"news_source": "yahoo_news", "program_id": None})),
        )
    with patch("app.api.admin_script_review.dispatch_job") as dispatch:
        response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "regenerate"})

    assert response.status_code == 200
    assert response.json()["episode_id"] == episode_id
    assert response.json()["status"] == "generating"
    dispatch.assert_called_once_with(response.json()["job_id"])
    with get_db_connection() as conn:
        assert conn.execute("SELECT status FROM episodes WHERE id=?", (episode_id,)).fetchone()["status"] == "generating"
        job = conn.execute("SELECT operation, episode_id, payload FROM generation_jobs WHERE id=?", (response.json()["job_id"],)).fetchone()
    assert (job["operation"], job["episode_id"]) == ("daily", episode_id)
    payload = json.loads(job["payload"])
    assert payload["program_id"] == "radio_news_neighbor"
    assert payload["news_source"] == "yahoo_news"
    assert payload["preserve_news_source"] is True


def test_reject_regenerate_falls_back_to_program_source_without_original_job(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET program_id='radio_tech_news' WHERE id=?", (episode_id,))
    with patch("app.api.admin_script_review.dispatch_job"):
        response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "regenerate"})
    assert response.status_code == 200
    with get_db_connection() as conn:
        job = conn.execute("SELECT payload FROM generation_jobs WHERE id=?", (response.json()["job_id"],)).fetchone()
    payload = json.loads(job["payload"])
    assert payload["program_id"] == "radio_tech_news"
    assert payload["news_source"] == "hatena_bookmark"


def test_reject_regenerate_falls_back_for_invalid_original_payload(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET program_id='radio_news_neighbor' WHERE id=?", (episode_id,))
        owner_id = conn.execute(
            "SELECT admin_user_id FROM sessions WHERE token=?",
            (next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"),),
        ).fetchone()["admin_user_id"]
        conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, client_ip_hash, episode_id, payload, status) "
            "VALUES (?, 'daily', ?, 'source-hash', 'source-ip', ?, '{invalid', 'completed')",
            (owner_id, f"invalid-source-{episode_id}", episode_id),
        )
    with patch("app.api.admin_script_review.dispatch_job"):
        response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "regenerate"})
    assert response.status_code == 200
    with get_db_connection() as conn:
        job = conn.execute("SELECT payload FROM generation_jobs WHERE id=?", (response.json()["job_id"],)).fetchone()
    assert json.loads(job["payload"])["news_source"] == "hatena_hotentry_all"


def test_reject_regenerate_falls_back_for_unexpected_original_news_source(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET program_id='radio_news_neighbor' WHERE id=?", (episode_id,))
        owner_id = conn.execute(
            "SELECT admin_user_id FROM sessions WHERE token=?",
            (next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"),),
        ).fetchone()["admin_user_id"]
        conn.execute(
            "INSERT INTO generation_jobs(owner_user_id, operation, idempotency_key, input_hash, client_ip_hash, episode_id, payload, status) "
            "VALUES (?, 'daily', ?, 'source-hash', 'source-ip', ?, ?, 'completed')",
            (owner_id, f"unexpected-source-{episode_id}", episode_id, json.dumps({"news_source": "unexpected"})),
        )
    with patch("app.api.admin_script_review.dispatch_job"):
        response = client.post(f"/admin/episodes/{episode_id}/reject", json={"action": "regenerate"})
    assert response.status_code == 200
    with get_db_connection() as conn:
        job = conn.execute("SELECT payload FROM generation_jobs WHERE id=?", (response.json()["job_id"],)).fetchone()
    payload = json.loads(job["payload"])
    assert payload["program_id"] == "radio_news_neighbor"
    assert payload["news_source"] == "hatena_hotentry_all"


def test_regeneration_runner_uses_preserved_source_with_program_snapshot(client):
    from types import SimpleNamespace
    from app.batch import run_daily

    episode_id, _ = _episode_with_script()
    job = {
        "episode_id": episode_id,
        "payload": json.dumps({
            "date": "2099-08-01", "program_id": "radio_news_neighbor",
            "news_source": "yahoo_news", "preserve_news_source": True,
        }),
    }
    profile = SimpleNamespace(id="radio_news_neighbor")
    with (
        patch("app.api.generate._episode_program_profile", return_value=profile),
        patch("app.batch.run_daily.cleanup_episodes", return_value={}),
        patch("app.batch.run_daily.run_radio_pipeline", return_value=None) as run_pipeline,
        patch("app.batch.run_daily._write_manifest"),
    ):
        run_daily.run_daily_job(job)
    assert run_pipeline.call_args.kwargs["news_source"] == "yahoo_news"
    assert run_pipeline.call_args.kwargs["program_profile"] is profile


def test_preview_audio_enforces_episode_daily_quota(client):
    from app.db.connection import get_db_connection

    episode_id, _ = _episode_with_script()
    with get_db_connection() as conn:
        admin_id = conn.execute(
            "SELECT admin_user_id FROM sessions WHERE token=?",
            (next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"),),
        ).fetchone()["admin_user_id"]
        conn.executemany(
            "INSERT INTO script_preview_rate_limits(admin_user_id, episode_id, created_at) "
            "VALUES (?, ?, datetime('now', '-2 hours'))",
            [(admin_id, episode_id)] * 30,
        )

    with patch("app.services.voicevox_client.VoicevoxClient.synthesize_line") as synthesize:
        response = client.post(f"/admin/episodes/{episode_id}/lines/0/preview-audio")

    assert response.status_code == 429
    synthesize.assert_not_called()


def test_review_notifications_are_unique_per_transition(client):
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService
    from app.services.script_review_service import move_episode_to_awaiting_review

    episode_id = EpisodeService().create_episode("2099-08-02", status="generating")
    with get_db_connection() as conn:
        admin_id = next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session")
        admin_id = conn.execute("SELECT admin_user_id FROM sessions WHERE token=?", (admin_id,)).fetchone()["admin_user_id"]
        conn.execute(
            "INSERT INTO push_subscriptions(subscription_id_hash, endpoint_hash, endpoint, p256dh, auth, admin_user_id) "
            "VALUES ('review-cycle-id', 'review-cycle-endpoint', 'https://push.example.test/review-cycle', 'key', 'auth', ?)",
            (admin_id,),
        )
    assert move_episode_to_awaiting_review(episode_id, "first review") is True
    assert move_episode_to_awaiting_review(episode_id, "recheck") is False
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET status='generating' WHERE id=?", (episode_id,))
    assert move_episode_to_awaiting_review(episode_id, "second review") is True
    with get_db_connection() as conn:
        events = conn.execute(
            "SELECT event_type FROM notification_outbox WHERE episode_id=? ORDER BY id", (episode_id,)
        ).fetchall()
        deliveries = conn.execute(
            "SELECT COUNT(*) FROM notification_deliveries d JOIN notification_outbox o ON o.id=d.outbox_id WHERE o.episode_id=?",
            (episode_id,),
        ).fetchone()[0]
        cycle = conn.execute("SELECT review_cycle FROM episodes WHERE id=?", (episode_id,)).fetchone()["review_cycle"]
    assert [row["event_type"] for row in events] == ["script_awaiting_review:1", "script_awaiting_review:2"]
    assert cycle == 2
    assert deliveries == 2


def test_legacy_push_subscription_can_be_associated_with_admin_session(client):
    import base64
    from app.db.connection import get_db_connection
    from app.api.push import _hash

    admin_session = next(cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session")
    client.cookies.delete("admin_session")
    keys = {
        "p256dh": base64.urlsafe_b64encode(bytes([4]) + bytes(range(1, 65))).decode().rstrip("="),
        "auth": base64.urlsafe_b64encode(bytes(range(16))).decode().rstrip("="),
    }
    registration = client.post("/push/subscriptions", json={"endpoint": "https://legacy.example.test/push", "keys": keys})
    assert registration.status_code == 200
    subscription_id = registration.json()["subscription_id"]
    with get_db_connection() as conn:
        assert conn.execute("SELECT admin_user_id FROM push_subscriptions WHERE subscription_id_hash=?", (_hash(subscription_id),)).fetchone()["admin_user_id"] is None

    # Restore the authenticated fixture cookie and bind the old opaque ID.
    client.cookies.set("admin_session", admin_session)
    associated = client.post("/push/subscriptions/associate", json={"subscription_id": subscription_id})
    assert associated.status_code == 204
    with get_db_connection() as conn:
        assert conn.execute("SELECT admin_user_id FROM push_subscriptions WHERE subscription_id_hash=?", (_hash(subscription_id),)).fetchone()["admin_user_id"] is not None


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
    rows = conn.execute("SELECT id, status, review_mode, review_cycle FROM episodes ORDER BY id").fetchall()
    assert [(row["status"], row["review_mode"], row["review_cycle"]) for row in rows] == [
        ("generating", "on_failure", 0),
        ("failed", "on_failure", 0),
    ]
    conn.close()
