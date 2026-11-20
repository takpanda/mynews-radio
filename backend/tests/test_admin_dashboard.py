"""運用ダッシュボード集計 API の契約テスト。"""

from datetime import datetime, timedelta, timezone

from app.db.connection import get_db_connection


def _ago(**delta) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**delta)


def _plain(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _episode(status: str, created_at: datetime) -> int:
    with get_db_connection() as conn:
        return conn.execute(
            "INSERT INTO episodes (episode_date, status, created_at) VALUES ('2026-01-01', ?, ?)",
            (status, _plain(created_at)),
        ).lastrowid


def _phase(episode_id, phase, started_at: datetime, duration_ms, failure_reason=None, attempt=1):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO episode_generation_phase_logs "
            "(episode_id, phase, attempt_no, result, started_at, duration_ms, failure_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (episode_id, phase, attempt, "failure" if failure_reason else "success",
             started_at.isoformat(), duration_ms, failure_reason),
        )


def _llm(phase, status, latency_ms, created_at: datetime, call_id: str):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO llm_call_logs (call_id, phase, provider, attempt, status, latency_ms, created_at) "
            "VALUES (?, ?, 'p', 1, ?, ?, ?)",
            (call_id, phase, status, latency_ms, _plain(created_at)),
        )


def test_dashboard_requires_owner_session(client):
    client.cookies.clear()
    response = client.get("/admin/dashboard/stats", headers={"Authorization": "Bearer test-admin-key"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Admin session required"}
    audit = client.get("/admin/audit-logs")
    assert audit.status_code == response.status_code

    client.cookies.set("admin_session", "expired-or-invalid")
    assert client.get("/admin/dashboard/stats").status_code == 401


def test_dashboard_rejects_invalid_range(client):
    for value in ("1d", "", "90d", "7D"):
        assert client.get("/admin/dashboard/stats", params={"range": value}).status_code == 422


def test_dashboard_empty_data(client):
    body = client.get("/admin/dashboard/stats").json()
    assert body["range"] == "7d"
    assert body["episodes"] == {"completed": 0, "failed": 0, "in_progress": 0, "success_rate": None}
    assert all(p["count"] == 0 and p["avg_ms"] is None and p["max_ms"] is None for p in body["phase_durations"])
    assert set(body["failures"]["by_reason"].values()) == {0}
    assert body["failures"]["llm_error_count"] == 0
    assert body["failures"]["recent"] == []
    assert body["llm"]["latency_by_phase"] == []
    assert body["llm"]["retry_count"] == 0 and body["llm"]["json_parse_failed_count"] == 0
    assert body["pending"] == {"unapproved_misreading_reports": 0, "awaiting_review_episodes": 0}


def test_dashboard_aggregates_metrics(client):
    now = _ago(hours=1)
    ok1 = _episode("completed", now)
    _episode("completed", now)
    bad = _episode("failed", now)
    _episode("discarded", now)
    _episode("generating", now)
    _episode("pending", now)
    review = _episode("awaiting_review", now)

    _phase(ok1, "synthesize", _ago(hours=2), 1000)
    _phase(bad, "synthesize", _ago(hours=3), 3000, failure_reason="tts_no_lines_succeeded")
    _phase(bad, "wav_combine", _ago(hours=1), None, failure_reason="wav_combine_failed")  # duration NULL は除外
    _phase(review, "mp3_encode", _ago(hours=2), 500)

    _llm("script", "success", 100, now, "c1")
    _llm("script", "retry", 300, now, "c2")
    _llm("script", "json_parse_failed", 200, now, "c3")
    _llm("review", "error", 50, now, "c4")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO misreading_reports (target_text, correct_reading, approved) VALUES ('a','b',0)")
        conn.execute("INSERT INTO misreading_reports (target_text, correct_reading, approved) VALUES ('c','d',0)")
        conn.execute("INSERT INTO misreading_reports (target_text, correct_reading, approved) VALUES ('e','f',1)")

    body = client.get("/admin/dashboard/stats").json()
    assert body["episodes"]["completed"] == 2
    assert body["episodes"]["failed"] == 1
    assert body["episodes"]["in_progress"] == 3  # pending / generating / awaiting_review
    assert abs(body["episodes"]["success_rate"] - 2 / 3) < 1e-9

    durations = {p["phase"]: p for p in body["phase_durations"]}
    assert durations["synthesize"] == {"phase": "synthesize", "count": 2, "avg_ms": 2000.0, "max_ms": 3000}
    assert durations["wav_combine"]["count"] == 0 and durations["wav_combine"]["avg_ms"] is None
    assert durations["mp3_encode"]["max_ms"] == 500

    assert body["failures"]["by_reason"]["tts_no_lines_succeeded"] == 1
    assert body["failures"]["by_reason"]["wav_combine_failed"] == 1
    assert body["failures"]["by_reason"]["script_missing"] == 0
    assert body["failures"]["llm_error_count"] == 1
    recent = body["failures"]["recent"]
    assert [r["reason"] for r in recent] == ["wav_combine_failed", "tts_no_lines_succeeded"]  # 新しい順
    assert recent[0]["episode_id"] == bad and recent[0]["phase"] == "wav_combine"

    latency = {r["phase"]: r for r in body["llm"]["latency_by_phase"]}
    assert latency["script"] == {"phase": "script", "call_count": 3, "avg_latency_ms": 200.0, "max_latency_ms": 300}
    assert body["llm"]["retry_count"] == 1
    assert body["llm"]["json_parse_failed_count"] == 1
    assert body["llm"]["anomalies_by_phase"] == [
        {"phase": "script", "retry_count": 1, "json_parse_failed_count": 1}
    ]
    assert body["pending"] == {"unapproved_misreading_reports": 2, "awaiting_review_episodes": 1}


def test_dashboard_recent_failures_capped_at_20(client):
    ep = _episode("failed", _ago(hours=1))
    for i in range(25):
        _phase(ep, "synthesize", _ago(minutes=i + 1), 10, failure_reason="build_exception", attempt=i + 1)
    assert len(client.get("/admin/dashboard/stats").json()["failures"]["recent"]) == 20


def test_dashboard_range_boundaries(client):
    # 7日の内側(6日23時間前) / 外側(7日1時間前) / 30日の外側(31日前)
    inside = _ago(days=6, hours=23)
    mid = _ago(days=7, hours=1)
    outside = _ago(days=31)
    ep_in = _episode("completed", inside)
    ep_mid = _episode("failed", mid)
    ep_out = _episode("failed", outside)
    _phase(ep_in, "synthesize", inside, 100)
    _phase(ep_mid, "synthesize", mid, 200, failure_reason="build_exception")
    _phase(ep_out, "synthesize", outside, 400, failure_reason="build_exception")
    _llm("script", "retry", 10, inside, "b1")
    _llm("script", "retry", 10, mid, "b2")
    _llm("script", "retry", 10, outside, "b3")
    with get_db_connection() as conn:  # 待ち件数は期間に関係なく全件
        conn.execute("UPDATE episodes SET status = 'awaiting_review' WHERE id = ?", (ep_out,))
        conn.execute("INSERT INTO misreading_reports (target_text, correct_reading, approved, created_at) "
                     "VALUES ('a','b',0,?)", (_plain(outside),))

    week = client.get("/admin/dashboard/stats", params={"range": "7d"}).json()
    assert (week["episodes"]["completed"], week["episodes"]["failed"]) == (1, 0)
    assert week["failures"]["by_reason"]["build_exception"] == 0
    assert week["phase_durations"][0]["count"] == 1
    assert week["llm"]["retry_count"] == 1

    month = client.get("/admin/dashboard/stats", params={"range": "30d"}).json()
    assert (month["episodes"]["completed"], month["episodes"]["failed"]) == (1, 1)
    assert month["failures"]["by_reason"]["build_exception"] == 1
    assert month["phase_durations"][0]["count"] == 2
    assert month["llm"]["retry_count"] == 2

    for body in (week, month):
        assert body["pending"] == {"unapproved_misreading_reports": 1, "awaiting_review_episodes": 1}
