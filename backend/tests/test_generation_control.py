"""生成開始時の利用上限・冪等性の受入テスト。"""

from app.services.generation_control import claim_job, finish_job


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
    response = client.post("/generate", json={"date": "2099-01-03"})
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
