import os
import threading
import time
from pathlib import Path
import sqlite3

import pytest


def _fresh_db(tmp_path):
    """Create a fresh DB file with schema + phase column migration."""
    db_file = tmp_path / "test.db"
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    schema_path = str(Path(__file__).parent.parent / "app" / "db" / "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN phase TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN generation_message TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DROP INDEX IF EXISTS idx_episodes_generating_date")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN seq INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_date_type ON episodes(episode_date, type)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE dictionary_entries ADD COLUMN notes TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE dictionary_entries ADD COLUMN source_misreading_report_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE misreading_reports ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE misreading_reports ADD COLUMN approved_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE misreading_reports ADD COLUMN approved_dictionary_entry_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_misreading_reports_approved ON misreading_reports(approved)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN key_points TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

    return db_file, ep_dir


@pytest.fixture(autouse=True)
def test_env(tmp_path, monkeypatch):
    """Set up fresh DB + env vars for each test function."""
    db_file, ep_dir = _fresh_db(tmp_path)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("EPISODES_DIR", str(ep_dir))
    # Tests must never mutate or depend on the real shared .102 busy counter.
    monkeypatch.setenv("THUMBNAIL_SERVICE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("GENERATE_RATE_LIMIT", "100/minute")
    # 既存の管理APIテストは有効なAPI_KEYを標準資格情報として使用する。
    # 未認証境界は専用の認証テストで明示的に確認する。
    monkeypatch.setenv("API_KEY", "test-admin-key")

    # Clear lru_cache on get_settings so lazy access picks up the new env vars
    from app import config as cfg_mod
    if hasattr(cfg_mod.get_settings, "cache_clear"):
        cfg_mod.get_settings.cache_clear()
    from app.api.generate import limiter
    limiter.reset()

    yield

    # 非同期のテスト処理が参照した設定値・レートリミット状態を次のテストへ持ち越さない。
    limiter.reset()
    if hasattr(cfg_mod.get_settings, "cache_clear"):
        cfg_mod.get_settings.cache_clear()


def _join_thread_group(threads, timeout):
    deadline = time.monotonic() + timeout
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if thread.is_alive():
            thread.join(timeout=remaining)

    alive = [thread.name for thread in threads if thread.is_alive()]
    if alive:
        pytest.fail(
            f"background worker threads still alive after {timeout:.2f}s: {', '.join(alive)}",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def no_daemon_thread_leaks(test_env):
    """Make all threads non-daemon so background threads from API tests
    can be tracked and joined before fixture cleanup, preventing orphaned
    threads from writing to cleaned-up temp dirs (//app errors)."""
    original_start = threading.Thread.start
    threads = []

    def _tracked_start(self):
        self.daemon = False
        threads.append(self)
        return original_start(self)

    threading.Thread.start = _tracked_start
    deadline = None
    timeout_reported = False

    def _join_started_threads():
        nonlocal deadline, timeout_reported
        if deadline is None:
            deadline = time.monotonic() + 5.0
        try:
            _join_thread_group(threads, max(0.0, deadline - time.monotonic()))
        except pytest.fail.Exception:
            if timeout_reported:
                return
            timeout_reported = True
            raise

    yield _join_started_threads
    threading.Thread.start = original_start
    _join_started_threads()


@pytest.fixture
def api_worker_teardown_state():
    state = {}
    yield state
    release_worker = state.get("release_on_cleanup")
    if release_worker:
        release_worker()
    if state.get("expect_pipeline_mock"):
        assert state.get("pipeline_mock_active") is True, (
            "API generation worker completed after the pipeline mock was restored"
        )


@pytest.fixture(autouse=True)
def isolate_external_telegram_notifications(test_env, monkeypatch):
    """Keep pipeline tests from sending Telegram notifications externally.

    Notification behavior is tested explicitly in test_telegram_notifier.py;
    tests that need to assert a pipeline notification can override these
    module-level seams with monkeypatch or patch.object.
    """
    from app.batch import orchestrate, radio_pipeline

    def _blocked_notification(**_kwargs):
        return False

    for module in (radio_pipeline, orchestrate):
        monkeypatch.setattr(module, "notify_failure", _blocked_notification)
        monkeypatch.setattr(module, "notify_success", _blocked_notification)


@pytest.fixture
def client(api_worker_teardown_state, no_daemon_thread_leaks):
    from app.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from app.db.connection import get_db_connection

    class GenerationTestClient(TestClient):
        """実生成APIの通常リクエストに一意なキーを付与するテストクライアント。"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._idempotency_counter = 0

        def post(self, url, *args, **kwargs):
            if url == "/generate" or "/synthesize" in url:
                headers = dict(kwargs.get("headers") or {})
                if "Idempotency-Key" not in headers:
                    self._idempotency_counter += 1
                    headers["Idempotency-Key"] = f"test-request-{self._idempotency_counter}"
                    kwargs["headers"] = headers
            return super().post(url, *args, **kwargs)

    with patch("app.api.generate.run_radio_pipeline", return_value=None):
        test_client = GenerationTestClient(app, headers={"Authorization": "Bearer test-admin-key"})
        with get_db_connection() as conn:
            from app.auth import hash_password
            conn.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                ("fixture-owner", hash_password("fixture-password")),
            )
        login = test_client.post(
            "/admin/login",
            json={"username": "fixture-owner", "password": "fixture-password"},
        )
        assert login.status_code == 200
        # Secure CookieはHTTPのTestClientから自動送信されないため明示的に設定する。
        test_client.cookies.set("admin_session", login.cookies["admin_session"])
        yield test_client
        # Keep the generation-pipeline mock installed until API background
        # workers finish; otherwise they can enter the real pipeline after
        # this fixture restores it and outlive the per-test DB configuration.
        before_join = api_worker_teardown_state.get("before_join")
        if before_join:
            before_join()
        no_daemon_thread_leaks()
