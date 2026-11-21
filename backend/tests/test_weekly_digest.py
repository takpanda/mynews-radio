"""週末ダイジェスト回(BEE-568)のテスト。"""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from app.batch import weekly_digest
from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _article(article_id, title, category="technology", score=5, summary="要約"):
    return {
        "id": article_id, "title": title, "source": "src", "url": f"https://example.test/{article_id}",
        "summary": summary, "category": category, "importance_score": score,
    }


def _insert_article(article_id, title, *, category="technology", score=5, summary="要約本文"):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO articles(id, title, source, url, text, summary, category, importance_score) "
            "VALUES (?, ?, 'src', ?, 'text', ?, ?, ?)",
            (article_id, title, f"https://example.test/{article_id}", summary, category, score),
        )


def _insert_episode(episode_type, status, completed_at, article_ids, episode_date="2026-11-17",
                    updated_at=None, audit_at=None):
    """completed_at(UTC)は完成確定時に登録される通知Outboxの時刻。

    updated_at(完成後のサムネイル更新等)と audit_at(生成ジョブの成功監査。レビュー待ち時点でも記録される)は
    完成時刻と別に指定でき、これらが集計に影響しないことの検証に使う。
    """
    with get_db_connection() as conn:
        episode_id = conn.execute(
            "INSERT INTO episodes(episode_date, status, type, updated_at) VALUES (?, ?, ?, ?)",
            (episode_date, status, episode_type, updated_at or completed_at),
        ).lastrowid
        for order, article_id in enumerate(article_ids, start=1):
            conn.execute(
                "INSERT INTO episode_items(episode_id, article_id, item_order, segment_text) VALUES (?, ?, ?, 't')",
                (episode_id, article_id, order),
            )
        if status == "completed":
            conn.execute(
                "INSERT INTO notification_outbox(event_type, episode_id, payload, created_at) "
                "VALUES ('daily_radio_completed', ?, '{}', ?)",
                (episode_id, completed_at),
            )
        if audit_at:
            conn.execute(
                "INSERT INTO audit_logs(operation, executed_at, result, episode_id) VALUES ('daily', ?, 'success', ?)",
                (audit_at.replace(" ", "T") + "+00:00", episode_id),
            )
    return episode_id


# ---------------------------------------------------------------------------
# ISO週
# ---------------------------------------------------------------------------


def test_iso_week_bounds_and_label():
    # 2026-11-22(日)は ISO週 2026-W47 (11/16 月 〜 11/22 日)
    assert weekly_digest.iso_week_bounds(date(2026, 11, 22)) == (date(2026, 11, 16), date(2026, 11, 22))
    assert weekly_digest.iso_week_bounds(date(2026, 11, 16)) == (date(2026, 11, 16), date(2026, 11, 22))
    assert weekly_digest.iso_week_label(date(2026, 11, 22)) == "2026-W47"
    # 年またぎはISO年で表す(2027-01-01 は 2026-W53)
    assert weekly_digest.iso_week_label(date(2027, 1, 1)) == "2026-W53"


def test_completion_window_is_monday_midnight_jst_to_next_day_midnight_jst():
    start, end = weekly_digest.completion_window_utc(date(2026, 11, 22))
    assert start == "2026-11-15 15:00:00"  # 月曜 0:00 JST
    assert end == "2026-11-22 14:59:59"  # 日曜 23:59:59 JST(両端を含む)


def test_completion_window_upper_bound_is_the_job_start_time():
    from datetime import datetime, timezone

    cutoff = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)  # 日曜 8:00 JST
    _, end = weekly_digest.completion_window_utc(date(2026, 11, 22), cutoff)
    assert end == "2026-11-21 23:00:00"
    # 起動時刻が対象日の翌0時より後でも、対象日の末尾(23:59:59 JST)を超えない
    late = datetime(2026, 11, 30, tzinfo=timezone.utc)
    assert weekly_digest.completion_window_utc(date(2026, 11, 22), late)[1] == "2026-11-22 14:59:59"


def test_find_week_digest_ignores_failed_and_other_weeks():
    svc = EpisodeService()
    svc.create_episode("2026-11-15", type="digest", status="completed")  # 前週
    svc.create_episode("2026-11-18", type="digest", status="failed")  # 今週だが失敗
    svc.create_episode("2026-11-19", type="radio", status="completed")  # 通常回
    assert weekly_digest.find_week_digest(date(2026, 11, 22)) is None
    digest_id = svc.create_episode("2026-11-22", type="digest", status="generating")
    assert weekly_digest.find_week_digest(date(2026, 11, 20))["id"] == digest_id


# ---------------------------------------------------------------------------
# 記事選定
# ---------------------------------------------------------------------------


def test_fetch_broadcast_articles_only_includes_completed_radio_in_the_week():
    for article_id in range(1, 8):
        _insert_article(article_id, f"記事{article_id}")
    _insert_article(8, "要約なし", summary="")
    # 月曜 0:00 JST = 日曜 15:00 UTC。境界の直前/直後。
    _insert_episode("radio", "completed", "2026-11-16 22:00:00", [1])  # 今週・放送済み
    _insert_episode("radio", "completed", "2026-11-15 15:00:00", [2])  # 境界ちょうど(含む)
    _insert_episode("radio", "completed", "2026-11-15 14:59:59", [3])  # 前週
    _insert_episode("radio", "failed", "2026-11-17 22:00:00", [4])  # 失敗回
    _insert_episode("radio", "generating", "2026-11-17 22:00:00", [5])  # 生成中
    _insert_episode("commentary", "completed", "2026-11-18 22:00:00", [6])  # 解説回
    _insert_episode("digest", "completed", "2026-11-19 22:00:00", [7])  # ダイジェスト回
    _insert_episode("radio", "completed", "2026-11-20 22:00:00", [8])  # 要約なし
    _insert_episode("radio", "completed", "2026-11-22 15:00:00", [1])  # 同じ記事の再放送(重複しない)
    _insert_episode("radio", "completed", "2026-11-22 14:00:00", [1])  # 日曜内(含む、重複しない)

    ids = sorted(a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22)))
    assert ids == [1, 2]


def test_completion_time_is_not_affected_by_later_episode_updates():
    """完成後のサムネイル更新等で updated_at が週をまたいでも、完成時刻で判定する。"""
    _insert_article(1, "今週完成・翌週に更新")
    _insert_article(2, "前週完成・今週に更新")
    _insert_episode("radio", "completed", "2026-11-20 22:00:00", [1], updated_at="2026-11-30 01:00:00")
    _insert_episode("radio", "completed", "2026-11-15 14:00:00", [2], updated_at="2026-11-18 01:00:00")

    assert [a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22))] == [1]


def test_review_held_last_week_and_completed_this_week_belongs_to_this_week():
    """前週にレビュー待ちとなり(成功監査は前週に記録)、今週に承認・音声完成した回は今週の集計に入る。"""
    _insert_article(1, "週またぎレビュー")
    _insert_article(2, "今週レビュー待ちのまま(未完成)")
    _insert_episode("radio", "completed", "2026-11-17 03:00:00", [1], audit_at="2026-11-12 21:30:00")
    _insert_episode("radio", "awaiting_review", "2026-11-17 03:00:00", [2], audit_at="2026-11-17 21:30:00")

    assert [a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22))] == [1]


def test_completion_right_before_job_start_is_included_even_if_audit_is_recorded_after():
    from datetime import datetime, timezone

    _insert_article(1, "起動直前に完成")
    # 完成(Outbox)は起動前、成功監査は起動後に記録された回
    _insert_episode("radio", "completed", "2026-11-21 22:59:59", [1], audit_at="2026-11-21 23:00:05")
    cutoff = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)

    assert [a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22), cutoff)] == [1]


def test_completion_in_the_same_second_as_job_start_is_not_missed():
    """Outboxは秒精度。起動時刻の小数秒を切り捨てても、同じ秒に完成した回は取りこぼさない。"""
    from datetime import datetime, timezone

    for i in (1, 2, 3):
        _insert_article(i, f"記事{i}")
    _insert_episode("radio", "completed", "2026-11-21 22:59:59", [1])  # 前の秒
    _insert_episode("radio", "completed", "2026-11-21 23:00:00", [2])  # 起動と同じ秒(起動は 23:00:00.9)
    _insert_episode("radio", "completed", "2026-11-21 23:00:01", [3])  # 次の秒(起動後)
    cutoff = datetime(2026, 11, 21, 23, 0, 0, 900000, tzinfo=timezone.utc)

    ids = sorted(a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22), cutoff))
    assert ids == [1, 2]


def test_episodes_completed_after_job_start_are_excluded():
    from datetime import datetime, timezone

    for i in (1, 2):
        _insert_article(i, f"記事{i}")
    _insert_episode("radio", "completed", "2026-11-21 22:30:00", [1])  # 起動(23:00 UTC)前に完成
    _insert_episode("radio", "completed", "2026-11-21 23:30:00", [2])  # キュー待機中に完成
    cutoff = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)

    ids = [a["id"] for a in weekly_digest.fetch_broadcast_articles(date(2026, 11, 22), cutoff)]
    assert ids == [1]


def test_pick_orders_by_importance_and_caps_max_articles():
    titles = _distinct_titles("Topic", 16) + _distinct_titles("Other", 16)
    candidates = [_article(i + 1, titles[i], category=f"c{i % 6}", score=i + 1) for i in range(29)]
    picked = weekly_digest.pick_digest_articles(candidates, max_articles=10)
    assert len(picked) == 10
    scores = [a["importance_score"] for a in picked]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 29


def test_pick_excludes_duplicate_topics():
    candidates = [
        _article(1, "OpenAI、ハラペーニョを発表", category="ai", score=9),
        _article(2, "OpenAI announces Jalapeño", category="ai", score=8),
        _article(3, "日銀が追加利上げを決定", category="economy", score=7),
    ]
    candidates.append({**_article(4, "別タイトルだが同一URL", category="economy", score=6), "url": candidates[2]["url"]})
    picked = weekly_digest.pick_digest_articles(candidates)
    assert [a["id"] for a in picked] == [1, 3]


def _distinct_titles(prefix, n):
    # titles_are_similar に類似扱いされないよう、語彙の異なるタイトルを使う。
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india",
             "juliet", "kilo", "lima", "mike", "november", "oscar", "papa"]
    return [f"{prefix} {words[i]} project launch {i * 7 + 3}" for i in range(n)]


def test_pick_does_not_concentrate_on_a_single_category():
    # tech が高スコアで大量にあっても、他カテゴリの記事が選ばれる
    candidates = [_article(i + 1, t, category="technology", score=10)
                  for i, t in enumerate(_distinct_titles("Tech", 15))]
    candidates += [_article(101 + i, t, category="society", score=3)
                   for i, t in enumerate(_distinct_titles("Society", 4))]
    candidates += [_article(201 + i, t, category="economy", score=2)
                   for i, t in enumerate(_distinct_titles("Economy", 4))]
    picked = weekly_digest.pick_digest_articles(candidates, max_articles=12)
    categories = [a["category"] for a in picked]
    assert len(picked) == 12
    assert categories.count("technology") == 5  # ceil(12 * 0.4)
    assert categories.count("society") == 4 and categories.count("economy") == 3


def test_pick_relaxes_category_cap_only_to_reach_minimum():
    candidates = [_article(i + 1, t, category="technology", score=10 - i % 3)
                  for i, t in enumerate(_distinct_titles("Tech", 14))]
    picked = weekly_digest.pick_digest_articles(candidates, max_articles=12)
    # 単一カテゴリしか無い週でも、最低件数までは補充する(それ以上は上限で止める)
    assert len(picked) == weekly_digest.DIGEST_CATEGORY_RELAX_MIN


# ---------------------------------------------------------------------------
# 台本生成・尺の目安
# ---------------------------------------------------------------------------


def test_length_target_is_ten_to_twelve_minutes_of_speech_regardless_of_article_count():
    chars_per_minute = 330
    assert weekly_digest.DIGEST_TARGET_CHARS_MIN / chars_per_minute == pytest.approx(10, abs=0.1)
    assert weekly_digest.DIGEST_TARGET_CHARS_MAX / chars_per_minute == pytest.approx(12, abs=0.2)
    for count in (1, 3, 6, 12):
        assert weekly_digest.target_chars_range(count) == (3300, 4000)
        assert weekly_digest.suggested_lines_count(count) == 46


def test_acceptable_length_range_is_about_nine_to_thirteen_minutes():
    assert weekly_digest.acceptable_chars_range(12) == (2970, 4400)
    assert weekly_digest.acceptable_chars_range(1) == (2970, 4400)
    assert 2970 / 330 == pytest.approx(9, abs=0.05) and 4400 / 330 == pytest.approx(13.3, abs=0.05)


@pytest.mark.parametrize("chars,ok", [
    (2000, False),   # 約6分
    (2969, False), (2970, True),   # 下限の境界
    (3650, True),
    (4400, True), (4401, False),   # 上限の境界
    (10000, False),  # 約30分
])
def test_length_within_target_boundaries(chars, ok):
    assert weekly_digest.length_within_target(chars, 12) is ok


class _FakeClient:
    prompts: list = []

    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def generate_json(self, prompt):
        _FakeClient.prompts.append(prompt)
        return self._response


def _patch_llm(monkeypatch, response):
    _FakeClient.prompts = []
    monkeypatch.setattr(weekly_digest, "create_llm_client", lambda *_a, **_k: _FakeClient(response))
    monkeypatch.setattr(weekly_digest, "set_llm_context", lambda *_a, **_k: None)


def test_generate_digest_script_builds_two_mc_script_from_summaries(monkeypatch, tmp_path):
    articles = [_article(1, "記事A", summary="Aの要約"), _article(2, "記事B", summary="Bの要約")]
    filler = "あ" * 3400  # 件数に依らず 3300〜4000字の目標に収める
    response = {
        "subtitle": "今週の振り返り",
        "lines": [
            {"speaker": "male", "text": "今週の総集編です。", "article_id": None, "section": "intro"},
            {"speaker": "female", "text": "記事Aの話。" + filler, "article_id": 1, "section": "news", "delivery": "warm"},
            {"speaker": "unknown", "text": "話者は補正される。", "article_id": 999, "section": "weird"},
            {"speaker": "male", "text": "   ", "article_id": 2, "section": "news"},
            "not-a-dict",
        ],
    }
    _patch_llm(monkeypatch, response)
    out = tmp_path / "7" / "script.json"

    count = weekly_digest.generate_digest_script(str(out), articles, date(2026, 11, 22), llm_provider="x", llm_model="y")

    assert count == 3
    script = json.loads(out.read_text(encoding="utf-8"))
    assert script["title"] == "ニュースのとなり 週末ダイジェスト 2026-W47"
    assert script["style"] == "dialogue"
    assert [line["speaker"] for line in script["lines"]] == ["male", "female", "male"]
    assert script["lines"][2]["article_id"] is None  # 選定外のIDは落とす
    assert script["lines"][2]["section"] == "news"
    # 入力は選定済みの既存要約だけ。管理画面の再現用に入力変数も保存される。
    assert "Aの要約" in _FakeClient.prompts[0] and "Bの要約" in _FakeClient.prompts[0]
    assert "2026-W47" in _FakeClient.prompts[0]
    context = json.loads((tmp_path / "7" / "prompt_context.json").read_text(encoding="utf-8"))
    assert context["article_count"] == 2


class _SeqClient(_FakeClient):
    responses: list = []

    def generate_json(self, prompt):
        _FakeClient.prompts.append(prompt)
        return _SeqClient.responses.pop(0)


def _script_response(total_chars, lines=10):
    each = total_chars // lines
    return {"subtitle": "s", "lines": [
        {"speaker": "male" if i % 2 == 0 else "female", "text": "あ" * each, "article_id": None, "section": "news"}
        for i in range(lines)
    ]}


def _patch_seq(monkeypatch, responses):
    _FakeClient.prompts = []
    _SeqClient.responses = list(responses)
    monkeypatch.setattr(weekly_digest, "create_llm_client", lambda *_a, **_k: _SeqClient(None))
    monkeypatch.setattr(weekly_digest, "set_llm_context", lambda *_a, **_k: None)


def _twelve_articles():
    return [_article(i, f"記事{i}") for i in range(1, 13)]


def test_out_of_range_scripts_are_regenerated_until_one_is_in_range(monkeypatch, tmp_path):
    _patch_seq(monkeypatch, [_script_response(800), _script_response(10000), _script_response(3600)])
    out = tmp_path / "script.json"
    count = weekly_digest.generate_digest_script(str(out), _twelve_articles(), date(2026, 11, 22), llm_provider="x")
    assert count == 10 and len(_FakeClient.prompts) == 3
    chars = weekly_digest.script_char_count(json.loads(out.read_text(encoding="utf-8")))
    assert weekly_digest.length_within_target(chars, 12)


@pytest.mark.parametrize("sizes", [
    [800, 900, 2000],        # 全て短い
    [10000, 9000, 12000],    # 全て長い
    [2000, 10000, 2900],     # 短い・長いが混在(長い方を優先して採用しない)
])
def test_script_is_not_published_when_every_attempt_is_out_of_range(monkeypatch, tmp_path, sizes):
    _patch_seq(monkeypatch, [_script_response(n) for n in sizes])
    out = tmp_path / "script.json"
    assert weekly_digest.generate_digest_script(str(out), _twelve_articles(), date(2026, 11, 22), llm_provider="x") == 0
    assert not out.exists()


def test_script_at_the_range_boundary_is_published(monkeypatch, tmp_path):
    _patch_seq(monkeypatch, [_script_response(2970)])
    out = tmp_path / "script.json"
    assert weekly_digest.generate_digest_script(str(out), _twelve_articles(), date(2026, 11, 22), llm_provider="x") == 10


def test_generate_digest_script_returns_zero_on_invalid_response(monkeypatch, tmp_path):
    _patch_llm(monkeypatch, {"lines": "oops"})
    assert weekly_digest.generate_digest_script(
        str(tmp_path / "script.json"), [_article(1, "A")], date(2026, 11, 22), llm_provider="x"
    ) == 0
    assert not (tmp_path / "script.json").exists()


# ---------------------------------------------------------------------------
# プロンプト管理(管理画面)
# ---------------------------------------------------------------------------


def test_digest_prompt_is_registered_for_admin_version_management(client):
    from app.db.migration import migrate_prompt_templates

    with get_db_connection() as conn:
        migrate_prompt_templates(conn)
        row = conn.execute(
            "SELECT pt.id, COUNT(pv.id) AS active FROM prompt_templates pt "
            "JOIN prompt_versions pv ON pv.template_id = pt.id AND pv.status = 'active' "
            "WHERE pt.template_key = 'generate_digest_script' AND pt.program_id IS NULL"
        ).fetchone()
    assert row["id"] is not None and row["active"] == 1

    listed = client.get("/admin/prompts")
    assert listed.status_code == 200
    assert any(p["template_key"] == "generate_digest_script" for p in listed.json())

    draft = client.post(
        f"/admin/prompts/{row['id']}/versions",
        json={"content": "{week_label}{article_count}{suggested_lines_count}{target_chars_min}{target_chars_max}{summaries_json}"},
    )
    assert draft.status_code == 201
    invalid = client.post(f"/admin/prompts/{row['id']}/versions", json={"content": "{week_label}"})
    assert invalid.status_code == 422


# ---------------------------------------------------------------------------
# 公開アーカイブのフィルター
# ---------------------------------------------------------------------------


def _public_episode(episode_type, episode_date, categories):
    svc = EpisodeService()
    episode_id = svc.create_episode(episode_date, audio_path="a.mp3", status="completed", type=episode_type)
    svc.update_episode_categories(episode_id, categories)
    ep_dir = os.path.join(os.environ["EPISODES_DIR"], str(episode_id))
    os.makedirs(ep_dir, exist_ok=True)
    Path(ep_dir, "a.mp3").write_bytes(b"dummy")
    return episode_id


def test_category_filter_separates_digest_from_regular_filters(client):
    tech = _public_episode("radio", "2026-11-17", ["テック・IT"])
    general = _public_episode("radio", "2026-11-18", ["ビジネス"])
    commentary = _public_episode("commentary", "2026-11-19", ["テック・IT"])
    digest = _public_episode("digest", "2026-11-22", ["テック・IT"])

    def ids(category):
        resp = client.get(f"/episodes?category={category}")
        assert resp.status_code == 200
        return {e["id"] for e in resp.json()}

    assert ids("digest") == {digest}
    assert ids("tech") == {tech}
    assert ids("general") == {general}
    assert ids("commentary") == {commentary}
    assert ids("all") == {tech, general, commentary, digest}


# ---------------------------------------------------------------------------
# 通常回への非影響・通知
# ---------------------------------------------------------------------------


def test_digest_does_not_change_regular_episode_counters():
    svc = EpisodeService()
    svc.create_episode("2026-11-22", type="digest", status="generating")
    assert svc.count_radio_by_date("2026-11-22") == 0
    episode_id, seq = svc.create_radio_episode("2026-11-22")
    assert seq == 0
    with get_db_connection() as conn:
        digest = conn.execute("SELECT status FROM episodes WHERE type = 'digest'").fetchone()
    assert digest["status"] == "generating"  # 通常回の古い生成中リセットに巻き込まれない
    assert svc.get_completed_episodes_for_feed() == []


def test_digest_completion_enqueues_one_weekly_event_and_keeps_daily_event():
    svc = EpisodeService()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO push_subscriptions(subscription_id_hash, endpoint_hash, endpoint, p256dh, auth) "
            "VALUES ('sid', 'eid', 'https://push.example.test/x', 'k', 'a')"
        )
    digest_id = svc.create_episode("2026-11-22", status="generating", type="digest")
    radio_id = svc.create_episode("2026-11-22", status="generating", type="radio")

    assert svc.complete_radio_episode_with_notification(digest_id) is True
    assert svc.complete_radio_episode_with_notification(digest_id) is True
    assert svc.complete_radio_episode_with_notification(radio_id) is True

    with get_db_connection() as conn:
        events = {r["episode_id"]: [] for r in conn.execute("SELECT episode_id FROM notification_outbox")}
        for r in conn.execute("SELECT episode_id, event_type, payload FROM notification_outbox"):
            events[r["episode_id"]].append((r["event_type"], json.loads(r["payload"])["url"]))
        deliveries = conn.execute(
            "SELECT o.event_type FROM notification_deliveries d JOIN notification_outbox o ON o.id = d.outbox_id"
        ).fetchall()
    assert events[digest_id] == [("weekly_digest_completed", f"/episodes/{digest_id}")]
    assert events[radio_id] == [("daily_radio_completed", f"/episodes/{radio_id}")]
    assert sorted(r["event_type"] for r in deliveries) == ["daily_radio_completed", "weekly_digest_completed"]


# ---------------------------------------------------------------------------
# パイプライン
# ---------------------------------------------------------------------------


def _fake_llm_selection(monkeypatch):
    from types import SimpleNamespace

    from app.services import llm_provider

    monkeypatch.setattr(
        llm_provider, "validate_provider_model", lambda *_a, **_k: SimpleNamespace(name="p", model="m")
    )


def _seed_week(n=5):
    for i in range(1, n + 1):
        _insert_article(i, f"まったく別の話題その{i}", category=f"c{i}", score=i)
    _insert_episode("radio", "completed", "2026-11-17 22:00:00", list(range(1, n + 1)))


def _patch_pipeline_parts(monkeypatch, tmp_path, calls):
    def fake_generate(output_path, articles, target_date, **kwargs):
        calls["articles"] = [a["id"] for a in articles]
        Path(output_path).write_text(json.dumps({
            "title": "t", "subtitle": "副題",
            "lines": [
                {"speaker": "male", "text": "導入", "article_id": None, "section": "intro"},
                {"speaker": "female", "text": "本編", "article_id": articles[0]["id"], "section": "news"},
            ],
        }), encoding="utf-8")
        return 2

    def fake_synthesize(directory, **kwargs):
        calls["synthesize"] = kwargs
        return 2

    def fake_build(directory, **kwargs):
        (Path(directory) / "episode.mp3").write_bytes(b"mp3")
        return {"title": "ニュースのとなり 週末ダイジェスト", "audio_path": "episode.mp3"}

    monkeypatch.setattr(weekly_digest, "generate_digest_script", fake_generate)
    monkeypatch.setattr(weekly_digest, "synthesize_episode", fake_synthesize)
    monkeypatch.setattr(weekly_digest, "build_episode", fake_build)
    monkeypatch.setattr(weekly_digest, "start_thumbnail_generation", lambda *_a, **_k: None)
    monkeypatch.setattr(weekly_digest, "notify_success", lambda **_k: calls.setdefault("notified", True))

    # 記事の再取得・再要約が起きたら失敗させる。
    def forbidden(*_a, **_k):
        raise AssertionError("digest must not re-import or re-summarize articles")

    import app.batch.import_articles as import_articles
    import app.batch.summarize_articles as summarize_articles

    monkeypatch.setattr(summarize_articles, "summarize_articles", forbidden)
    monkeypatch.setattr(import_articles, "import_articles_by_source", forbidden)
    assert not hasattr(weekly_digest, "summarize_articles")


def test_pipeline_creates_completed_digest_with_two_mc_fishs2pro(monkeypatch, tmp_path):
    _seed_week()
    _fake_llm_selection(monkeypatch)
    calls: dict = {}
    _patch_pipeline_parts(monkeypatch, tmp_path, calls)
    episode_id = EpisodeService().create_episode("2026-11-22", status="generating", type="digest")

    result = weekly_digest.run_digest_pipeline(
        episode_id, episode_date="2026-11-22", tts_engine="fishs2pro"
    )

    assert isinstance(result, dict)
    episode = EpisodeService().get_episode(episode_id)
    assert episode["type"] == "digest" and episode["status"] == "completed"
    assert episode["audio_path"] == "episode.mp3"
    assert calls["articles"] == [5, 4, 3, 2, 1]  # 放送済み記事を重要度順に
    assert calls["synthesize"]["tts_engine"] == "fishs2pro"
    assert calls["synthesize"]["speaker_male"] and calls["synthesize"]["speaker_female"]  # MC 2名
    assert calls["notified"] is True
    items = EpisodeService().get_episode_items(episode_id)
    assert [i["article_id"] for i in items] == [None, 5]
    with get_db_connection() as conn:
        outbox = conn.execute("SELECT event_type FROM notification_outbox WHERE episode_id = ?", (episode_id,)).fetchall()
    assert [r["event_type"] for r in outbox] == ["weekly_digest_completed"]


def test_pipeline_skips_only_when_no_broadcast_articles():
    episode_id = EpisodeService().create_episode("2026-11-22", status="generating", type="digest")

    result = weekly_digest.run_digest_pipeline(episode_id, episode_date="2026-11-22")

    assert result is weekly_digest.PipelineResult.NO_CONTENT
    # 試行の記録として failed で残る(公開されず、通知もされない)
    assert EpisodeService().get_episode(episode_id)["status"] == "failed"
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0


def test_pipeline_generates_even_with_a_single_broadcast_article(monkeypatch, tmp_path):
    _insert_article(1, "唯一の記事")
    _insert_episode("radio", "completed", "2026-11-17 22:00:00", [1])
    _fake_llm_selection(monkeypatch)
    calls: dict = {}
    _patch_pipeline_parts(monkeypatch, tmp_path, calls)
    episode_id = EpisodeService().create_episode("2026-11-22", status="generating", type="digest")

    assert isinstance(weekly_digest.run_digest_pipeline(episode_id, episode_date="2026-11-22"), dict)
    assert calls["articles"] == [1]
    assert EpisodeService().get_episode(episode_id)["status"] == "completed"


def test_pipeline_marks_failed_when_synthesis_fails(monkeypatch, tmp_path):
    _seed_week()
    _fake_llm_selection(monkeypatch)
    calls: dict = {}
    _patch_pipeline_parts(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(weekly_digest, "synthesize_episode", lambda *_a, **_k: 0)
    monkeypatch.setattr(weekly_digest, "notify_failure", lambda **_k: None)
    episode_id = EpisodeService().create_episode("2026-11-22", status="generating", type="digest")

    assert weekly_digest.run_digest_pipeline(episode_id, episode_date="2026-11-22") is None
    assert EpisodeService().get_episode(episode_id)["status"] == "failed"
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE event_type = 'weekly_digest_completed'"
        ).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 週次バッチ(二重生成防止・キュー)
# ---------------------------------------------------------------------------


def _run_batch(monkeypatch, batch_date="2026-11-22"):
    from app.batch import run_weekly_digest

    monkeypatch.setenv("BATCH_DATE", batch_date)
    run_weekly_digest.main()


def _digests():
    with get_db_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT id, status, episode_date FROM episodes WHERE type = 'digest'")]


def test_running_the_job_twice_in_the_same_iso_week_creates_one_digest(monkeypatch):
    calls = []

    def fake_pipeline(episode_id, *, episode_date, tts_engine=None, **_kw):
        calls.append((episode_id, episode_date, tts_engine))
        EpisodeService().complete_radio_episode_with_notification(episode_id)
        return {"title": "ok"}

    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", fake_pipeline)

    _run_batch(monkeypatch, "2026-11-22")
    _run_batch(monkeypatch, "2026-11-22")
    _run_batch(monkeypatch, "2026-11-18")  # 同一ISO週の別日

    assert len(calls) == 1
    digests = _digests()
    assert len(digests) == 1 and digests[0]["status"] == "completed"
    with get_db_connection() as conn:
        job = conn.execute("SELECT operation, status FROM generation_jobs").fetchone()
    assert (job["operation"], job["status"]) == ("weekly_digest", "completed")


def test_next_iso_week_creates_a_new_digest(monkeypatch):
    monkeypatch.setattr(
        weekly_digest, "run_digest_pipeline",
        lambda episode_id, **_kw: EpisodeService().complete_radio_episode_with_notification(episode_id) and {"t": 1},
    )
    _run_batch(monkeypatch, "2026-11-22")
    _run_batch(monkeypatch, "2026-11-29")
    assert sorted(d["episode_date"] for d in _digests()) == ["2026-11-22", "2026-11-29"]


def test_failed_digest_can_be_retried_in_the_same_week(monkeypatch):
    outcomes = iter([None, {"title": "ok"}])

    def fake_pipeline(episode_id, **_kw):
        outcome = next(outcomes)
        if outcome is None:
            EpisodeService().update_episode_status(episode_id, "failed")
        else:
            EpisodeService().complete_radio_episode_with_notification(episode_id)
        return outcome

    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", fake_pipeline)
    _run_batch(monkeypatch)
    _run_batch(monkeypatch)
    assert sorted(d["status"] for d in _digests()) == ["completed", "failed"]


def test_digest_waits_behind_an_active_daily_job_in_the_shared_queue(monkeypatch):
    """通常回が実行中(active)なら、ダイジェストは同じFIFOで待機し同時実行しない。"""
    from app.db.migration import ensure_generation_system_owner
    from app.services.generation_control import enqueue_job

    with get_db_connection() as conn:
        owner_id = ensure_generation_system_owner(conn)
    daily = enqueue_job(owner_id, "daily", "daily-2026-11-22", {"date": "2026-11-22"},
                        episode_date="2026-11-22", client_ip="cron", dispatch=False)
    assert daily.status == "active"
    ran = []
    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", lambda *a, **k: ran.append(1))

    _run_batch(monkeypatch)

    assert ran == []
    with get_db_connection() as conn:
        job = conn.execute("SELECT status FROM generation_jobs WHERE operation = 'weekly_digest'").fetchone()
        episode = conn.execute("SELECT status FROM episodes WHERE type = 'digest'").fetchone()
    assert job["status"] == "waiting" and episode["status"] == "waiting"


# ---------------------------------------------------------------------------
# cron
# ---------------------------------------------------------------------------


def test_entrypoint_registers_weekly_digest_cron_for_sunday_8am_jst():
    entrypoint = (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'DIGEST_SCHEDULE="${DIGEST_CRON_SCHEDULE:-0 23 * * 6}"' in entrypoint  # 土曜23:00 UTC = 日曜 8:00 JST
    assert "run_weekly_digest.py" in entrypoint
    # 通常回(毎日6:00 JST)の定義は変更しない
    assert 'SCHEDULE="${CRON_SCHEDULE:-0 21 * * *}"' in entrypoint
    assert "run_daily.py" in entrypoint


def test_admin_can_render_digest_prompt_from_saved_episode_input(client, monkeypatch, tmp_path):
    from app.api import admin_prompts
    from app.db.migration import migrate_prompt_templates

    episode_dir = admin_prompts.EPISODES_DIR / "91"
    episode_dir.mkdir(parents=True)
    variables = {
        "week_label": "2026-W47", "article_count": 1, "suggested_lines_count": 45,
        "target_chars_min": 3300, "target_chars_max": 4000, "summaries_json": '[{"id": 1, "summary": "保存済み要約"}]',
    }
    (episode_dir / "prompt_context.json").write_text(json.dumps(variables, ensure_ascii=False), encoding="utf-8")
    with get_db_connection() as conn:
        migrate_prompt_templates(conn)
        conn.execute("INSERT INTO episodes(id, episode_date, type) VALUES (91, '2026-11-22', 'digest')")
        version_id = conn.execute(
            "SELECT pv.id FROM prompt_versions pv JOIN prompt_templates pt ON pt.id = pv.template_id "
            "WHERE pt.template_key = 'generate_digest_script' AND pv.status = 'active'"
        ).fetchone()[0]

    rendered = client.post(f"/admin/prompts/versions/{version_id}/render", json={"episode_id": 91})

    assert rendered.status_code == 200, rendered.text
    assert "保存済み要約" in rendered.json()["prompt"]
    assert "2026-W47" in rendered.json()["prompt"]


def test_rerun_after_a_no_content_week_can_generate_once_articles_exist(monkeypatch):
    """記事が無く生成しなかった週でも、後から記事が増えれば同じ週に再実行できる。"""
    _fake_llm_selection(monkeypatch)
    calls: dict = {}
    _patch_pipeline_parts(monkeypatch, None, calls)
    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", weekly_digest.run_digest_pipeline)

    _run_batch(monkeypatch)  # 対象記事なし → 公開されない試行記録(failed)だけが残る
    assert [d["status"] for d in _digests()] == ["failed"]
    _insert_article(1, "あとから放送された記事")
    _insert_episode("radio", "completed", "2026-11-17 22:00:00", [1])

    _run_batch(monkeypatch)
    _run_batch(monkeypatch)  # 3回目は既存ダイジェストがあるためスキップ

    assert sorted(d["status"] for d in _digests()) == ["completed", "failed"]
    assert calls["articles"] == [1]


def test_job_payload_pins_the_job_start_time_as_cutoff(monkeypatch):
    seen = {}

    def fake_pipeline(episode_id, *, episode_date, tts_engine=None, cutoff=None, **_kw):
        seen["cutoff"] = cutoff
        EpisodeService().complete_radio_episode_with_notification(episode_id)
        return {"title": "ok"}

    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", fake_pipeline)
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc)
    _run_batch(monkeypatch)
    assert before <= seen["cutoff"] <= datetime.now(timezone.utc)


def test_reruns_after_the_24h_job_retention_still_get_distinct_keys(monkeypatch):
    """記事なしの週を、生成ジョブの保持期限(24時間)を過ぎてから連続再実行しても409にならない。"""
    _fake_llm_selection(monkeypatch)

    def purge_jobs():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM generation_jobs")

    _run_batch(monkeypatch)  # 記事なし → failed の試行が1件
    purge_jobs()
    _run_batch(monkeypatch)  # 24時間後(旧ジョブ削除済み)
    purge_jobs()
    _run_batch(monkeypatch)  # さらに24時間後
    assert [d["status"] for d in _digests()] == ["failed", "failed", "failed"]

    # 記事が増えたら、ジョブ削除後でも生成できる
    purge_jobs()
    _insert_article(1, "あとから")
    _insert_episode("radio", "completed", "2026-11-17 22:00:00", [1])
    calls: dict = {}
    _patch_pipeline_parts(monkeypatch, None, calls)
    _run_batch(monkeypatch)
    assert sorted(d["status"] for d in _digests()) == ["completed", "failed", "failed", "failed"]


def test_concurrent_start_with_the_same_attempt_key_is_skipped_not_raised(monkeypatch):
    from app.batch import run_weekly_digest
    from app.db.migration import ensure_generation_system_owner
    from app.services.generation_control import enqueue_job

    with get_db_connection() as conn:
        owner_id = ensure_generation_system_owner(conn)
    key = weekly_digest.digest_idempotency_key(date(2026, 11, 22))
    # 別プロセスが同じキーで(別のcutoffで)先に登録済み
    enqueue_job(owner_id, "weekly_digest", key, {"date": "2026-11-22", "cutoff": "x"},
                episode_date="2026-11-22", episode_type="digest", client_ip="cron", dispatch=False)
    ran = []
    monkeypatch.setattr(weekly_digest, "run_digest_pipeline", lambda *a, **k: ran.append(1))

    monkeypatch.setenv("BATCH_DATE", "2026-11-22")
    run_weekly_digest.main()  # 例外にならない
    assert ran == [] and len(_digests()) == 1
