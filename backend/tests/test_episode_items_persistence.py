"""ラジオ回の完了パスで episode_items が保存されること(BEE-593)のテスト。"""

import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.batch import weekly_digest
from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

LINES = [
    {"speaker": "male", "text": "一本目", "article_id": 1},
    {"speaker": "female", "text": "二本目", "article_id": 2},
    {"speaker": "male", "text": "つなぎ"},
]


def _items(episode_id):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT article_id, item_order, segment_text, audio_generation_id "
            "FROM episode_items WHERE episode_id = ? ORDER BY item_order",
            (episode_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _insert_articles():
    with get_db_connection() as conn:
        for aid in (1, 2):
            conn.execute(
                "INSERT OR REPLACE INTO articles(id, title, source, url, text, summary, category, importance_score) "
                "VALUES (?, ?, 'src', ?, 't', '要約', 'technology', 5)",
                (aid, f"記事{aid}", f"https://example.test/bee593/{aid}"),
            )


def _write_script(path, lines=LINES):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"lines": lines}, ensure_ascii=False), encoding="utf-8")


def _assert_items(episode_id, count=3):
    items = _items(episode_id)
    assert [i["item_order"] for i in items] == list(range(1, count + 1))
    assert [i["article_id"] for i in items] == [1, 2, None][:count]
    assert items[0]["audio_generation_id"] == f"ep{episode_id}-seg1"
    assert items[0]["segment_text"] == "一本目"


def test_replace_episode_items_is_idempotent(tmp_path):
    _insert_articles()
    service = EpisodeService()
    episode_id = service.create_episode("2099-09-01", status="completed", type="radio")
    script = tmp_path / "script.json"
    _write_script(script)

    assert service.replace_episode_items_from_script(episode_id, str(script)) == 3
    assert service.replace_episode_items_from_script(episode_id, str(script)) == 3

    _assert_items(episode_id)


def test_replace_keeps_existing_rows_when_script_is_invalid(tmp_path):
    _insert_articles()
    service = EpisodeService()
    episode_id = service.create_episode("2099-09-02", status="completed", type="radio")
    script = tmp_path / "script.json"
    _write_script(script)
    service.replace_episode_items_from_script(episode_id, str(script))
    script.write_text("{broken", encoding="utf-8")

    try:
        service.replace_episode_items_from_script(episode_id, str(script))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid script should raise")

    assert len(_items(episode_id)) == 3


def _run_stream_synthesize(episode_id):
    from app.api.generate import SynthesizeRequest, _stream_synthesize

    with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
         patch("app.api.generate.synthesize_episode", return_value=1), \
         patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
         patch("app.api.generate.notify_success"):
        return b"".join(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="fishs2pro")))


def test_stream_synthesize_persists_items_and_is_idempotent():
    _insert_articles()
    service = EpisodeService()
    episode_id = service.create_episode("2099-09-03", status="completed", type="radio")
    _write_script(Path(os.environ["EPISODES_DIR"]) / str(episode_id) / "script.json")

    _run_stream_synthesize(episode_id)
    _assert_items(episode_id)
    _run_stream_synthesize(episode_id)
    _assert_items(episode_id)


def test_stream_synthesize_fails_episode_when_items_cannot_be_saved():
    service = EpisodeService()
    episode_id = service.create_episode("2099-09-04", status="completed", type="radio")
    _write_script(Path(os.environ["EPISODES_DIR"]) / str(episode_id) / "script.json")

    with patch.object(EpisodeService, "replace_episode_items_from_script", side_effect=OSError("boom")):
        payload = _run_stream_synthesize(episode_id)

    assert b"persist_error" in payload
    assert service.get_episode(episode_id)["status"] == "failed"


def test_orchestrate_run_persists_items_and_digest_can_fetch_articles(tmp_path):
    from app.batch import orchestrate

    _insert_articles()
    today = date.today().isoformat()

    def fake_generate_script(script_path, **_kwargs):
        _write_script(script_path)
        return len(LINES)

    with patch.object(orchestrate, "EPISODES_DIR", str(tmp_path)), \
         patch.object(orchestrate, "import_articles_by_source", return_value=(1, 0)), \
         patch.object(orchestrate, "summarize_articles", return_value=2), \
         patch.object(orchestrate, "generate_script", side_effect=fake_generate_script), \
         patch.object(orchestrate, "review_script", return_value={"revised": False, "review_count": 0}), \
         patch.object(orchestrate, "should_run_final_validation", return_value=False), \
         patch.object(orchestrate, "_record_script_revision"), \
         patch.object(orchestrate, "_episode_review_mode", return_value="auto"), \
         patch.object(orchestrate, "synthesize_episode", return_value=1), \
         patch.object(orchestrate, "build_episode", return_value={"duration_seconds": 1}), \
         patch.object(orchestrate, "_update_episode_audio"), \
         patch.object(orchestrate, "notify_success"):
        orchestrate.run(today)

    with get_db_connection() as conn:
        episode_id = conn.execute(
            "SELECT id FROM episodes WHERE type = 'radio' AND episode_date = ? ORDER BY id DESC LIMIT 1",
            (today,),
        ).fetchone()["id"]
        assert conn.execute("SELECT status FROM episodes WHERE id = ?", (episode_id,)).fetchone()["status"] == "completed"
    _assert_items(episode_id)

    articles = weekly_digest.fetch_broadcast_articles(date.today())
    assert {a["id"] for a in articles} >= {1, 2}
