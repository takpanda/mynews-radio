"""管理者向けエピソード詳細ログ API の契約テスト。"""

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService


def _insert_job(
    episode_id: int,
    *,
    operation: str = "generate",
    status: str = "completed",
    suffix: str = "default",
    claimed_at: str = "2026-08-14 10:00:00",
    finished_at: str = "2026-08-14 10:03:00",
) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO generation_jobs (owner_user_id, operation, idempotency_key, input_hash, "
            "client_ip_hash, episode_id, status, claimed_at, finished_at) "
            "VALUES (1, ?, ?, 'input-hash-not-exposed', 'ip-hash', ?, ?, ?, ?)",
            (operation, f"detail-log-{episode_id}-{operation}-{suffix}", episode_id, status, claimed_at, finished_at),
        )
        return cursor.lastrowid


def _insert_phase(episode_id: int, job_id: int | None, phase: str, attempt_no: int, *, result=None) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO episode_generation_phase_logs "
            "(episode_id, generation_job_id, phase, attempt_no, result, tts_engine, started_at, ended_at, "
            "duration_ms, line_success_count, line_total_count, failure_reason) "
            "VALUES (?, ?, ?, ?, ?, 'voicevox', '2026-08-14 10:00:05', '2026-08-14 10:02:31', "
            "146000, 1, 1, NULL)",
            (episode_id, job_id, phase, attempt_no, result),
        )
        return cursor.lastrowid


def test_episode_logs_require_owner_session(client):
    client.cookies.clear()
    response = client.get("/admin/episodes/1/logs", headers={"Authorization": "Bearer test-admin-key"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Admin session required"}

    client.cookies.set("admin_session", "expired-or-invalid")
    response = client.get("/admin/episodes/1/logs")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired session"}


def test_episode_logs_return_integrated_timeline_and_latest_synthesis_lines(client):
    episode_id = EpisodeService().create_episode("2026-08-14", status="completed", seq=1)
    job_id = _insert_job(episode_id)
    first_phase_id = _insert_phase(episode_id, job_id, "synthesize", 1, result="success")
    latest_phase_id = _insert_phase(episode_id, job_id, "synthesize", 2, result=None)
    _insert_phase(episode_id, job_id, "wav_combine", 1, result="failure")
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs (operation, actor_user_id, generation_job_id, executed_at, result, accepted, "
            "started_at, ended_at, episode_id) VALUES "
            "('generate', 1, ?, '2026-08-14 10:00:00', 'started', 1, '2026-08-14 10:00:00', NULL, ?), "
            "('generate', 1, ?, '2026-08-14 10:03:00', 'success', 1, '2026-08-14 10:00:00', '2026-08-14 10:03:00', ?)",
            (job_id, episode_id, job_id, episode_id),
        )
        conn.execute(
            "INSERT INTO episode_items (episode_id, article_id, item_order) VALUES (?, NULL, 1)",
            (episode_id,),
        )
        conn.execute(
            "INSERT INTO episode_generation_line_logs "
            "(phase_log_id, episode_id, script_line_index, speaker, section, delivery, tts_engine, "
            "speaking_rate, processing_duration_ms, synth_result, retry_count, wav_file, silence_before_sec, "
            "start_time_sec, failure_reason) VALUES (?, ?, 1, 'male', 'intro', 'neutral', 'voicevox', "
            "1.0, 850, 'success', 0, '001.wav', 0.0, 3.2, NULL)",
            (latest_phase_id, episode_id),
        )

    response = client.get(f"/admin/episodes/{episode_id}/logs")
    assert response.status_code == 200
    body = response.json()
    assert body["episode"]["id"] == episode_id
    assert body["episode"]["created_at"].endswith("+00:00")
    assert body["generation_jobs"] == [{
        "id": job_id, "operation": "generate", "owner": {"id": 1, "username": "fixture-owner"},
        "client_ip_hash": "ip-hash", "status": "completed",
        "claimed_at": "2026-08-14T10:00:00+00:00", "finished_at": "2026-08-14T10:03:00+00:00",
    }]
    timeline_keys = [
        (event["occurred_at"], 0 if event["source"] == "audit" else 1, event["source_id"])
        for event in body["timeline"]
    ]
    assert timeline_keys == sorted(timeline_keys)
    assert any(event["result"] == "incomplete" and event["source_id"] == latest_phase_id for event in body["timeline"])
    assert body["lines"] == [{
        "phase_log_id": latest_phase_id, "attempt_no": 2, "script_line_index": 1, "article_id": None,
        "speaker": "male", "section": "intro", "delivery": "neutral", "tts_engine": "voicevox",
        "speaking_rate": 1.0, "processing_duration_ms": 850, "synth_result": "success", "retry_count": 0,
        "wav_file": "001.wav", "silence_before_sec": 0.0, "start_time_sec": 3.2, "failure_reason": None,
    }]
    assert first_phase_id not in [line["phase_log_id"] for line in body["lines"]]
    assert "input-hash-not-exposed" not in response.text

    past_response = client.get(f"/admin/episodes/{episode_id}/logs?phase_log_id={first_phase_id}")
    assert past_response.status_code == 200
    assert past_response.json()["lines"] == []


def test_episode_logs_normalize_llm_call_created_at_to_utc_iso(client):
    episode_id = EpisodeService().create_episode("2026-08-14")
    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO llm_call_logs "
            "(call_id, episode_id, phase, provider, model, base_url, attempt, status, created_at) "
            "VALUES (?, ?, 'script', 'ollama', 'model', 'http://ollama.local', 1, 'success', ?)",
            [
                ("naive-created-at", episode_id, "2026-08-14 10:00:00"),
                ("utc-created-at", episode_id, "2026-08-14T10:01:00+00:00"),
            ],
        )

    response = client.get(f"/admin/episodes/{episode_id}/logs")

    assert response.status_code == 200
    assert [call["created_at"] for call in response.json()["llm_calls"]] == [
        "2026-08-14T10:00:00+00:00",
        "2026-08-14T10:01:00+00:00",
    ]


def test_episode_logs_return_empty_collections_when_no_logs(client):
    episode_id = EpisodeService().create_episode("2026-08-14")
    response = client.get(f"/admin/episodes/{episode_id}/logs")
    assert response.status_code == 200
    assert response.json()["generation_jobs"] == []
    assert response.json()["timeline"] == []
    assert response.json()["lines"] == []


def test_episode_logs_return_failed_generation_and_do_not_expose_secrets(client):
    raw_ip = "203.0.113.34"
    idempotency_key = "idempotency-key-must-not-be-returned"
    idempotency_key_hash = "idempotency-key-hash-must-not-be-returned"
    input_hash = "input-hash-must-not-be-returned"
    script_text = "script-text-must-not-be-returned"
    source_url = "https://example.invalid/private-source"
    exception_text = "exception-body-must-not-be-returned"
    file_path = "/private/audio/output.wav"
    episode_id = EpisodeService().create_episode(
        "2026-08-14", script_text=script_text, source_url=source_url, status="failed",
    )
    later_job_id = _insert_job(
        episode_id, status="failed", suffix="later", claimed_at="2026-08-14 11:00:00",
    )
    earlier_job_id = _insert_job(
        episode_id, operation="synthesize", status="failed", suffix="earlier", claimed_at="2026-08-14 09:00:00",
    )
    synthesis_phase_id = _insert_phase(episode_id, earlier_job_id, "synthesize", 1, result="failure")
    _insert_phase(episode_id, later_job_id, "wav_combine", 1, result="failure")
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE generation_jobs SET idempotency_key = ?, input_hash = ?, client_ip_hash = ? WHERE id = ?",
            (f"{idempotency_key}-{raw_ip}", input_hash, "sha256-ip-hash", earlier_job_id),
        )
        conn.execute(
            "UPDATE episode_generation_phase_logs SET failure_reason = 'wav_combine_failed' "
            "WHERE episode_id = ? AND phase = 'wav_combine'",
            (episode_id,),
        )
        conn.execute(
            "INSERT INTO audit_logs (operation, actor_user_id, generation_job_id, idempotency_key_hash, input_hash, "
            "executed_at, result, accepted, rejection_reason, episode_id) "
            "VALUES ('synthesize', 1, ?, ?, ?, '2026-08-14 09:01:00', 'failure', 1, ?, ?)",
            (earlier_job_id, idempotency_key_hash, input_hash, exception_text, episode_id),
        )
        conn.execute(
            "INSERT INTO episode_generation_line_logs "
            "(phase_log_id, episode_id, script_line_index, synth_result, retry_count, wav_file, failure_reason) "
            "VALUES (?, ?, 1, 'failure', 2, ?, 'tts_request_failed')",
            (synthesis_phase_id, episode_id, file_path),
        )

    response = client.get(f"/admin/episodes/{episode_id}/logs")
    assert response.status_code == 200
    body = response.json()
    assert [job["id"] for job in body["generation_jobs"]] == [earlier_job_id, later_job_id]
    assert any(event["source"] == "audit" and event["result"] == "failure" for event in body["timeline"])
    assert any(
        event["phase"] == "wav_combine" and event["result"] == "failure"
        and event["reason"] == "wav_combine_failed"
        for event in body["timeline"]
    )
    assert body["lines"][0]["failure_reason"] == "tts_request_failed"
    assert body["lines"][0]["wav_file"] is None
    assert all(event["reason"] != exception_text for event in body["timeline"])
    for forbidden in (
        raw_ip, idempotency_key, idempotency_key_hash, input_hash, script_text,
        source_url, exception_text, file_path,
    ):
        assert forbidden not in response.text


def test_episode_logs_reject_missing_other_episode_and_non_synthesis_phase_ids(client):
    episode_id = EpisodeService().create_episode("2026-08-14")
    other_episode_id = EpisodeService().create_episode("2026-08-15")
    own_combine_id = _insert_phase(episode_id, None, "wav_combine", 1, result="success")
    other_synthesis_id = _insert_phase(other_episode_id, None, "synthesize", 1, result="success")

    for phase_log_id in (999999, own_combine_id, other_synthesis_id):
        response = client.get(f"/admin/episodes/{episode_id}/logs?phase_log_id={phase_log_id}")
        assert response.status_code == 404
        assert response.json() == {"detail": "Synthesis phase log not found"}

    missing_episode = client.get("/admin/episodes/999999/logs")
    assert missing_episode.status_code == 404
    assert missing_episode.json() == {"detail": "Episode not found"}
