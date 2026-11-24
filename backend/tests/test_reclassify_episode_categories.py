import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reclassify_episode_categories.py"


def _load():
    spec = importlib.util.spec_from_file_location("reclassify_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _episode(date, *, audio=True, raw_categories=None, dir_name=None, episode_type=None):
    svc = EpisodeService()
    kwargs = {"episode_date": date, "audio_path": "a.mp3", "status": "completed"}
    if episode_type:
        kwargs["type"] = episode_type
    episode_id = svc.create_episode(**kwargs)
    base = os.environ["EPISODES_DIR"]
    d = os.path.join(base, dir_name or str(episode_id))
    os.makedirs(d, exist_ok=True)
    if audio:
        Path(d, "a.mp3").write_bytes(b"x")
    Path(d, "script.json").write_text(json.dumps({"lines": [{"text": "スマホの話"}]}), encoding="utf-8")
    if raw_categories is not None:
        with get_db_connection() as conn:
            conn.execute("UPDATE episodes SET categories = ? WHERE id = ?", (raw_categories, episode_id))
    return episode_id


def _raw(episode_id):
    with get_db_connection() as conn:
        return conn.execute("SELECT categories FROM episodes WHERE id = ?", (episode_id,)).fetchone()[0]


def _run(module, argv, selector, responses_api=False):
    with patch.object(module, "select_episode_categories", side_effect=selector), \
         patch.object(module, "validate_provider_model") as v, \
         patch("sys.argv", ["x", *argv]):
        v.return_value.responses_api = responses_api
        return module.main()


def test_targets_match_public_rules_and_legacy_date_dir(client):
    module = _load()
    public = _episode("2099-02-01")
    no_audio = _episode("2099-02-02", audio=False)
    legacy = _episode("2099-02-03", audio=False, dir_name="2099-02-03")
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET audio_path='a.mp3' WHERE id=?", (legacy,))
    Path(os.environ["EPISODES_DIR"], "2099-02-03", "a.mp3").write_bytes(b"x")
    categorized = _episode("2099-02-04", raw_categories='["テック・IT"]')

    ids = [r["id"] for r in module._targets(None, False)]
    assert public in ids and legacy in ids
    assert no_audio not in ids and categorized not in ids

    seen = []
    _run(module, [], lambda script, summaries, **kw: seen.append(script) or ["テック・IT"])
    assert any(os.path.join("2099-02-03", "script.json") in s for s in seen)


def test_dry_run_writes_nothing(client):
    module = _load()
    episode_id = _episode("2099-03-01")

    def selector(script, summaries, **kw):
        # 実LLMクライアント経路のログ抑止を確認するため、ログ記録関数を直接呼ぶ
        from app.services import ollama_client
        ollama_client._record_llm_call(object(), attempt=1, status="ok", prompt_text="p")
        return ["テック・IT"]

    with patch("app.services.llm_call_log_service.get_db_connection", side_effect=AssertionError("write")):
        assert _run(module, [], selector) == 0
    assert _raw(episode_id) == "[]"
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llm_call_logs").fetchone()[0] == 0


def test_apply_backs_up_raw_value_and_restore_recovers(client, tmp_path):
    module = _load()
    legacy_raw = '["旧ラベル"'  # 不正なJSON（正規化すると []）
    episode_id = _episode("2099-04-01", raw_categories=legacy_raw)
    backup = tmp_path / "backup.jsonl"

    assert _run(module, ["--apply", "--backup-file", str(backup)], lambda *a, **k: ["AI・先端技術"]) == 0
    assert json.loads(_raw(episode_id)) == ["AI・先端技術"]
    assert json.loads(backup.read_text(encoding="utf-8").splitlines()[0]) == {
        "id": episode_id, "categories": legacy_raw,
    }

    assert _run(module, ["--restore", str(backup)], lambda *a, **k: []) == 0
    assert _raw(episode_id) == legacy_raw


def test_empty_selection_does_not_overwrite(client, tmp_path):
    module = _load()
    episode_id = _episode("2099-05-01")
    assert _run(module, ["--apply", "--backup-file", str(tmp_path / "b.jsonl")], lambda *a, **k: []) == 1
    assert _raw(episode_id) == "[]"


def test_backup_file_is_never_reused(client, tmp_path):
    module = _load()
    episode_id = _episode("2099-06-01", raw_categories='["旧"')
    backup = tmp_path / "b.jsonl"
    assert _run(module, ["--apply", "--backup-file", str(backup)], lambda *a, **k: ["テック・IT"]) == 0
    first = backup.read_text(encoding="utf-8")
    # 同じバックアップ先での再実行は更新前に拒否され、ファイル・DBとも変わらない
    assert _run(module, ["--apply", "--all", "--backup-file", str(backup)], lambda *a, **k: ["国際"]) == 2
    assert backup.read_text(encoding="utf-8") == first
    assert json.loads(_raw(episode_id)) == ["テック・IT"]
    _run(module, ["--restore", str(backup)], lambda *a, **k: [])
    assert _raw(episode_id) == '["旧"'


def test_dry_run_skips_inference_for_auth_stateful_provider(client):
    module = _load()
    _episode("2099-07-01")
    called = []
    rc = _run(module, [], lambda *a, **k: called.append(1) or ["テック・IT"], responses_api=True)
    assert rc == 0 and not called


def test_legacy_date_dir_passes_episode_id_for_program_prompt(client):
    module = _load()
    episode_id = _episode("2099-08-01", audio=False, dir_name="2099-08-01")
    with get_db_connection() as conn:
        conn.execute("UPDATE episodes SET program_id='radio_tech_news' WHERE id=?", (episode_id,))
    Path(os.environ["EPISODES_DIR"], "2099-08-01", "a.mp3").write_bytes(b"x")
    kwargs_seen = {}
    _run(module, [], lambda *a, **k: kwargs_seen.update(k) or ["テック・IT"])
    assert kwargs_seen["episode_id"] == episode_id

    # カテゴリ選定側: 明示IDで番組別プロンプトを選ぶ（パスからは推定できない）
    from app.services import episode_category_service as svc
    seen = {}
    script = Path(os.environ["EPISODES_DIR"], "2099-08-01", "script.json")
    with patch.object(svc, "program_id_for_episode", side_effect=lambda i: seen.setdefault("id", i)), \
         patch.object(svc, "create_llm_client", side_effect=RuntimeError("stop")):
        svc.select_episode_categories(str(script), "x", llm_provider="p", episode_id=episode_id)
    assert seen["id"] == episode_id
