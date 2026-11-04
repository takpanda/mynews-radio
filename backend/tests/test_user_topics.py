import sqlite3
from pathlib import Path

import pytest

from app.services import settings_service


@pytest.fixture
def topic_db(monkeypatch, tmp_path):
    """スキーマを適用した使い捨てDBを、get_db_connection の接続先にする。"""
    db_path = tmp_path / "topics.db"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    from app.db import connection
    monkeypatch.setattr(connection, "get_settings", lambda: FakeSettings)
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    with connection.get_db_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    return db_path


def _topic(name="ローカルLLM", description="Ollama等", weight="high", is_active=True):
    return dict(name=name, description=description, weight=weight, is_active=is_active)


def test_validation_rejects_invalid_topic_fields():
    invalid = [
        _topic(name="   "),
        _topic(name="x" * 41),
        _topic(description="x" * 201),
        # 末尾の空白を除いて200字でも、入力そのものが201字なら拒否する
        _topic(description="y" * 199 + "  "),
        _topic(weight="urgent"),
        _topic(is_active="yes"),
    ]
    for values in invalid:
        with pytest.raises(ValueError):
            settings_service._validate_user_topic(
                values["name"], values["description"], values["weight"], values["is_active"]
            )
    # 境界値は通る（名前40字、説明200字、前後空白は除去して判定）
    value = settings_service._validate_user_topic(" " + "x" * 40 + " ", "y" * 200, "low", True)
    assert value["name"] == "x" * 40
    assert len(value["description"]) == 200


def test_create_list_update_delete_topic(topic_db):
    created = settings_service.create_user_topic(**_topic(name=" Kubernetes ", weight="medium"))
    assert created["name"] == "Kubernetes"
    assert created["is_active"] is True
    topic_id = created["id"]

    listed = settings_service.get_user_topics()
    assert [item["id"] for item in listed] == [topic_id]
    assert listed[0]["weight"] == "medium"

    updated = settings_service.update_user_topic(topic_id, **_topic(name="K8s", weight="low", is_active=False))
    assert updated == {"id": topic_id, "name": "K8s", "description": "Ollama等", "weight": "low", "is_active": False}

    settings_service.delete_user_topic(topic_id)
    assert settings_service.get_user_topics() == []
    with pytest.raises(KeyError):
        settings_service.delete_user_topic(topic_id)
    with pytest.raises(KeyError):
        settings_service.update_user_topic(topic_id, **_topic())


def test_duplicate_name_is_rejected_case_insensitively(topic_db):
    settings_service.create_user_topic(**_topic(name="Ollama"))
    with pytest.raises(settings_service.TopicNameConflictError):
        settings_service.create_user_topic(**_topic(name="ollama"))
    other = settings_service.create_user_topic(**_topic(name="量子化"))
    with pytest.raises(settings_service.TopicNameConflictError):
        settings_service.update_user_topic(other["id"], **_topic(name="OLLAMA"))


def test_duplicate_name_is_rejected_for_non_ascii_case_and_width(topic_db):
    # SQLite の NOCASE は非ASCIIを区別するため、Unicode の大文字小文字・全角半角も同一視する。
    settings_service.create_user_topic(**_topic(name="Ä-Modell"))
    with pytest.raises(settings_service.TopicNameConflictError):
        settings_service.create_user_topic(**_topic(name="ä-modell"))
    settings_service.create_user_topic(**_topic(name="ＡＩ"))
    with pytest.raises(settings_service.TopicNameConflictError):
        settings_service.create_user_topic(**_topic(name="ai"))
    other = settings_service.create_user_topic(**_topic(name="量子化"))
    with pytest.raises(settings_service.TopicNameConflictError):
        settings_service.update_user_topic(other["id"], **_topic(name="Ai"))


def test_description_length_is_checked_before_trimming(topic_db):
    boundary = settings_service.create_user_topic(**_topic(name="境界", description="y" * 200))
    assert len(boundary["description"]) == 200
    with pytest.raises(ValueError):
        settings_service.create_user_topic(**_topic(name="空白", description="y" * 200 + " "))


def test_delete_rolls_back_cache_removal_when_topic_delete_fails(topic_db):
    # トピック本体の削除で失敗を注入し、先に消した判定キャッシュが戻ることを確認する。
    from app.db import connection
    topic = settings_service.create_user_topic(**_topic())
    with connection.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO article_topic_matches (article_id, topic_id, relevance, fingerprint) "
            "VALUES (1, ?, 3, 'abc')",
            (topic["id"],),
        )
        conn.execute(
            "CREATE TRIGGER fail_user_topic_delete BEFORE DELETE ON user_topics "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(sqlite3.Error):
        settings_service.delete_user_topic(topic["id"])
    with connection.get_db_connection() as conn:
        topics = conn.execute("SELECT COUNT(*) FROM user_topics").fetchone()[0]
        matches = conn.execute("SELECT COUNT(*) FROM article_topic_matches").fetchone()[0]
    assert (topics, matches) == (1, 1)


def test_limit_of_twenty_topics_is_enforced(topic_db):
    for index in range(settings_service.TOPIC_MAX_COUNT):
        settings_service.create_user_topic(**_topic(name=f"topic-{index}"))
    with pytest.raises(ValueError):
        settings_service.create_user_topic(**_topic(name="one-too-many"))
    assert len(settings_service.get_user_topics()) == settings_service.TOPIC_MAX_COUNT


def test_delete_removes_cached_matches_explicitly(topic_db):
    # SQLite の外部キーは無効のため、削除時に判定キャッシュも明示的に消えること。
    from app.db import connection
    topic = settings_service.create_user_topic(**_topic())
    with connection.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO article_topic_matches (article_id, topic_id, relevance, fingerprint) "
            "VALUES (1, ?, 3, 'abc')",
            (topic["id"],),
        )
    settings_service.delete_user_topic(topic["id"])
    with connection.get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM article_topic_matches").fetchone()[0]
    assert count == 0


def test_get_topics_returns_empty_list_on_database_failure(monkeypatch):
    def broken_connection():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(settings_service, "get_db_connection", broken_connection)
    assert settings_service.get_user_topics() == []


def test_migrate_user_topics_is_idempotent_and_keeps_existing_settings(tmp_path):
    from app.db.migration import migrate_user_topics

    conn = sqlite3.connect(str(tmp_path / "legacy.db"))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE user_settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "priority_themes TEXT NOT NULL, excluded_themes TEXT NOT NULL, duration_preset TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO user_settings VALUES (1, '[\"technology\"]', '[]', 'short')")
    assert migrate_user_topics(conn) is True
    assert migrate_user_topics(conn) is True
    row = conn.execute("SELECT priority_themes, duration_preset FROM user_settings").fetchone()
    assert (row[0], row[1]) == ('["technology"]', "short")
    conn.execute("INSERT INTO user_topics (name, name_key, weight) VALUES ('a', 'a', 'high')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO user_topics (name, name_key, weight) VALUES ('A', 'a', 'low')")
    conn.close()


def test_topics_api_crud_limits_and_failures(client, monkeypatch):
    from app.api import settings as settings_api

    listed = client.get("/settings/topics")
    assert listed.status_code == 200
    assert listed.json()["topics"] == []
    assert listed.json()["limits"] == {"max_topics": 20, "name_max_length": 40, "description_max_length": 200}

    created = client.post("/settings/topics", json={"name": "ローカルLLM", "weight": "high"})
    assert created.status_code == 201
    topic_id = created.json()["id"]
    assert client.post("/settings/topics", json={"name": "ローカルllm", "weight": "low"}).status_code == 409
    assert client.post("/settings/topics", json={"name": "x", "weight": "urgent"}).status_code == 422
    assert client.post("/settings/topics", json={"name": "x", "weight": "low", "extra": 1}).status_code == 422

    updated = client.put(f"/settings/topics/{topic_id}", json={"name": "ローカルLLM", "weight": "medium"})
    assert updated.status_code == 200
    assert updated.json()["weight"] == "medium"
    assert client.put("/settings/topics/9999", json={"name": "y", "weight": "low"}).status_code == 404
    assert client.delete("/settings/topics/9999").status_code == 404

    assert client.delete(f"/settings/topics/{topic_id}").status_code == 204
    assert client.get("/settings/topics").json()["topics"] == []

    # 上限: 20件まで登録でき、21件目は422
    for index in range(20):
        assert client.post("/settings/topics", json={"name": f"t{index}", "weight": "low"}).status_code == 201
    assert client.post("/settings/topics", json={"name": "t20", "weight": "low"}).status_code == 422

    # DB障害: 一覧は空配列、書き込みは503
    monkeypatch.setattr(settings_api, "create_user_topic", lambda **_: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert client.post("/settings/topics", json={"name": "z", "weight": "low"}).status_code == 503
    monkeypatch.setattr(settings_service, "get_db_connection", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert client.get("/settings/topics").json()["topics"] == []
    assert client.put("/settings/topics/1", json={"name": "y", "weight": "low"}).status_code == 503
    assert client.delete("/settings/topics/1").status_code == 503


def test_settings_response_shape_is_unchanged(client):
    client.post("/settings/topics", json={"name": "A", "weight": "high"})
    assert set(client.get("/settings").json()) == {"priority_themes", "excluded_themes", "duration_preset"}


def test_topics_endpoints_require_authentication():
    from app.main import app
    from fastapi.testclient import TestClient

    anonymous = TestClient(app)
    assert anonymous.get("/settings/topics").status_code in (401, 403)
    assert anonymous.post("/settings/topics", json={"name": "a", "weight": "low"}).status_code in (401, 403)
