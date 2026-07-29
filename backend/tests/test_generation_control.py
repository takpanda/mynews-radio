"""生成開始時の利用上限・冪等性の受入テスト。"""

from datetime import datetime, timezone
import time
import pytest

from app.services.generation_control import GenerationControlError, claim_job, finish_job
from app.db.connection import get_db_connection


def test_idempotency_replays_same_episode_and_rejects_changed_input(client):
    headers = {"Idempotency-Key": "generation-replay-1"}
    first = client.post("/generate", json={"date": "2099-01-01"}, headers=headers)
    second = client.post("/generate", json={"date": "2099-01-01"}, headers=headers)
    changed = client.post("/generate", json={"date": "2099-01-02"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["episode_id"] == first.json()["episode_id"]
    assert changed.status_code == 409


def test_idempotency_key_is_required(client):
    response = client.post("/generate", json={"date": "2099-01-03"}, headers={"Idempotency-Key": ""})
    assert response.status_code == 400


def test_active_generation_returns_retry_after(client):
    claim = claim_job(1, "generate", "active-claim", {"date": "2099-01-04"})
    response = client.post(
        "/generate",
        json={"date": "2099-01-05"},
        headers={"Idempotency-Key": "active-claim-2"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    finish_job(claim.job_id, False)


def test_daily_generation_limit_is_shared_by_operations(client):
    claims = []
    for i in range(10):
        claims.append(claim_job(1, "generate" if i % 2 else "synthesize", f"daily-{i}", {"i": i}))
        finish_job(claims[-1].job_id, True)
    for claim in claims:
        finish_job(claim.job_id, True)

    response = client.post(
        "/generate",
        json={"date": "2099-01-06"},
        headers={"Idempotency-Key": "daily-over"},
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_synthesis_duplicate_reports_active_completed_and_failed_state(client):
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-01-07", status="generating")
    for key, expected_event, expected_status, finished in (
        ("synth-active", "progress", "running", None),
        ("synth-completed", "complete", "completed", True),
        ("synth-failed", "error", "failed", False),
    ):
        claim = claim_job(1, "synthesize", key, {"episode_id": episode_id, "body": {"tts_engine": "voicevox"}})
        if finished is not None:
            finish_job(claim.job_id, finished)
        response = client.post(
            f"/episodes/{episode_id}/synthesize",
            json={"tts_engine": "voicevox"},
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert f"event: {expected_event}" in body
        assert f'"status": "{expected_status}"' in body
        if finished is None:
            finish_job(claim.job_id, False)


def test_failed_claim_allows_next_start_and_jst_boundary_retry_is_positive(client):
    from app.services.generation_control import _seconds_until_jst_midnight

    failed = claim_job(1, "generate", "failed-then-retry", {"date": "2099-01-08"})
    finish_job(failed.job_id, False)
    retried = claim_job(1, "generate", "failed-then-retry-2", {"date": "2099-01-08"})
    assert retried.duplicate is False
    finish_job(retried.job_id, False)

    near_midnight = datetime(2026, 7, 29, 14, 59, 59, tzinfo=timezone.utc)
    assert _seconds_until_jst_midnight(near_midnight) == 1


def test_endpoints_share_daily_limit_and_return_jst_boundary_retry_after(client, monkeypatch):
    import app.services.generation_control as control
    from app.api import generate as generate_api
    from app.services.episode_service import EpisodeService

    fixed_now = datetime(2026, 7, 29, 14, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(control, "_utc_now", lambda: fixed_now)

    def complete_generation(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")

    monkeypatch.setattr(generate_api, "_run_generation", complete_generation)

    def complete_synthesis(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")
        yield b"event: complete\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_stream_synthesize", complete_synthesis)

    for i in range(10):
        if i % 2:
            response = client.post(
                "/generate", json={"date": f"2099-02-{i + 1:02d}"},
                headers={"Idempotency-Key": f"endpoint-daily-{i}"},
            )
        else:
            episode_id = EpisodeService().create_episode(f"2099-02-{i + 1:02d}", status="generating")
            response = client.post(
                f"/episodes/{episode_id}/synthesize", json={"tts_engine": "voicevox"},
                headers={"Idempotency-Key": f"endpoint-daily-{i}"},
            )
        assert response.status_code == 200
        for _ in range(100):
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT status FROM generation_jobs WHERE idempotency_key = ?",
                    (f"endpoint-daily-{i}",),
                ).fetchone()
            if row and row["status"] != "active":
                break
            time.sleep(0.01)

    response = client.post(
        "/generate", json={"date": "2099-02-20"},
        headers={"Idempotency-Key": "endpoint-daily-over"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def test_ip_and_global_active_limits_apply_across_owners_and_operations(client):
    from app.auth import hash_password

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            ("second-owner", hash_password("password")),
        )
        second_owner_id = conn.execute(
            "SELECT id FROM admin_users WHERE username = ?", ("second-owner",)
        ).fetchone()[0]

    same_ip = claim_job(1, "generate", "ip-active-1", {"n": 1}, client_ip="10.0.0.1")
    try:
        with pytest.raises(GenerationControlError) as exc_info:
            claim_job(second_owner_id, "synthesize", "ip-active-2", {"n": 2}, client_ip="10.0.0.1")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 60
        assert exc_info.value.args[0] == "Another generation from this IP is already running"
    finally:
        finish_job(same_ip.job_id, False)

    other_ip = claim_job(1, "generate", "global-active-1", {"n": 3}, client_ip="10.0.0.2")
    try:
        with pytest.raises(GenerationControlError) as exc_info:
            claim_job(second_owner_id, "synthesize", "global-active-2", {"n": 4}, client_ip="10.0.0.3")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 60
        assert exc_info.value.args[0] == "The generation service is busy"
    finally:
        finish_job(other_ip.job_id, False)


def test_ip_and_global_daily_limits_are_enforced(client):
    from app.auth import hash_password

    with get_db_connection() as conn:
        for username in ("daily-owner-2", "daily-owner-3"):
            conn.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                (username, hash_password("password")),
            )
        owner_ids = [
            row[0] for row in conn.execute(
                "SELECT id FROM admin_users WHERE username LIKE 'daily-owner-%' ORDER BY id"
            ).fetchall()
        ]

    # Ten completed jobs from one IP reach the IP-scoped daily quota first.
    for index in range(10):
        owner_id = owner_ids[index % len(owner_ids)]
        claim = claim_job(owner_id, "generate", f"ip-daily-{index}", {"n": index}, client_ip="10.0.1.1")
        finish_job(claim.job_id, True)
    with pytest.raises(GenerationControlError) as exc_info:
        claim_job(1, "synthesize", "ip-daily-over", {"n": 11}, client_ip="10.0.1.1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after > 0

def test_global_daily_limit_is_enforced_across_ips(client):
    for index in range(10):
        claim = claim_job(1, "generate", f"global-daily-{index}", {"n": index}, client_ip=f"10.0.2.{index + 1}")
        finish_job(claim.job_id, True)
    with pytest.raises(GenerationControlError) as exc_info:
        claim_job(1, "synthesize", "global-daily-over", {"n": 12}, client_ip="10.0.2.99")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after > 0


def test_untrusted_proxy_ip_headers_are_ignored_for_generation_and_synthesis(client, monkeypatch):
    from app.api import generate as generate_api
    from app.audit import hash_value
    from app.services.episode_service import EpisodeService

    def complete_generation(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")

    def complete_synthesis(episode_id, _body):
        EpisodeService().update_episode_status(episode_id, "completed")
        yield b"event: complete\ndata: {}\n\n"

    monkeypatch.setattr(generate_api, "_run_generation", complete_generation)
    monkeypatch.setattr(generate_api, "_stream_synthesize", complete_synthesis)

    generated = client.post(
        "/generate",
        json={"date": "2099-08-01"},
        headers={
            "Idempotency-Key": "relay-generate",
            "X-Proxy-Client-IP": "198.51.100.10",
            "X-Proxy-Auth": "not-a-deployment-contract",
        },
    )
    assert generated.status_code == 200
    for _ in range(100):
        with get_db_connection() as conn:
            status = conn.execute(
                "SELECT status FROM generation_jobs WHERE idempotency_key = 'relay-generate'"
            ).fetchone()["status"]
        if status != "active":
            break
        time.sleep(0.01)

    episode_id = EpisodeService().create_episode("2099-08-02", status="generating")
    synthesized = client.post(
        f"/episodes/{episode_id}/synthesize",
        json={"tts_engine": "voicevox"},
        headers={
            "Idempotency-Key": "relay-synthesize",
            "X-Proxy-Client-IP": "198.51.100.11",
            "X-Proxy-Auth": "not-a-deployment-contract",
        },
    )
    assert synthesized.status_code == 200

    spoofed = client.post(
        "/generate",
        json={"date": "2099-08-03"},
        headers={
            "Idempotency-Key": "untrusted-ip",
            "X-Proxy-Client-IP": "198.51.100.99",
            "X-Proxy-Auth": "wrong-secret",
        },
    )
    assert spoofed.status_code == 200

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT idempotency_key, client_ip_hash FROM generation_jobs "
            "WHERE idempotency_key IN ('relay-generate', 'relay-synthesize', 'untrusted-ip') "
            "ORDER BY idempotency_key"
        ).fetchall()
    by_key = {row["idempotency_key"]: row["client_ip_hash"] for row in rows}
    assert by_key["relay-generate"] != hash_value("198.51.100.10")
    assert by_key["relay-synthesize"] != hash_value("198.51.100.11")
    assert by_key["untrusted-ip"] != hash_value("198.51.100.99")
