"""Tests for the manually-triggered AIVIS user dictionary sync."""

from unittest.mock import Mock, patch


def _entry(client, surface="新語", reading="しんご", active=1):
    response = client.post(
        "/admin/dictionary",
        json={"word": surface, "reading": reading, "category": "test"},
    )
    entry_id = response.json()["id"]
    if not active:
        client.patch(f"/admin/dictionary/{entry_id}/status", json={"status": "inactive"})
    return entry_id


def test_sync_adds_only_selected_active_entries(client):
    selected = _entry(client, "選択語", "せんたくご")
    _entry(client, "選択外", "せんたくがい")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [selected]})

    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert response.json()["deleted"] == 0
    fake.add_word.assert_called_once_with("選択語", "せんたくご")


def test_sync_requires_confirmation_for_existing_surface(client):
    entry_id = _entry(client, "既存語", "きご")
    fake = Mock()
    fake.list_words.return_value = [{"uuid": "remote-1", "surface": "既存語", "pronunciation": "きぞんご"}]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    data = response.json()
    assert response.status_code == 200
    assert data["updated"] == 0
    assert data["details"][0]["status"] == "confirmation_required"
    fake.update_word.assert_not_called()


def test_sync_updates_only_after_confirmation_and_skips_same_reading(client):
    overwrite_id = _entry(client, "更新語", "こうしん")
    same_id = _entry(client, "同一語", "どういつ")
    fake = Mock()
    fake.list_words.return_value = [
        {"uuid": "remote-1", "surface": "更新語", "pronunciation": "きゅうしん"},
        {"uuid": "remote-2", "surface": "同一語", "pronunciation": "どういつ"},
    ]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [overwrite_id, same_id], "overwrite_confirmed": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["updated"] == 1
    assert any(item["reason"] == "same_reading" for item in data["details"])
    fake.update_word.assert_called_once_with("remote-1", "更新語", "こうしん")


def test_sync_skips_missing_and_inactive(client):
    inactive_id = _entry(client, "無効語", "むこうご", active=0)
    fake = Mock()
    fake.list_words.return_value = []
    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [inactive_id, 999999]},
        )
    assert response.status_code == 200
    assert response.json()["skipped"] == 2
    fake.add_word.assert_not_called()


def test_sync_returns_503_when_aivis_is_unavailable(client):
    entry_id = _entry(client, "接続不能確認", "せつぞくふのうかくにん")
    fake = Mock()
    fake.list_words.side_effect = OSError("connection refused")
    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]}
        )
    assert response.status_code == 503
    assert "connection" not in response.text.lower()


def test_sync_does_not_call_aivis_when_no_active_entry_is_selected(client):
    inactive_id = _entry(client, "無効選択", "むこうせんたく", active=0)
    with patch("app.api.dictionary_sync.AivisUserDictClient") as aivis_client:
        response = client.post(
            "/admin/user_dict_sync", json={"dictionary_entry_ids": [inactive_id, 999999]}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["added"] == data["updated"] == data["errors"] == 0
    assert data["deleted"] == 0
    assert data["skipped"] == 2
    aivis_client.assert_not_called()


def test_sync_continues_after_individual_add_failure(client):
    first = _entry(client, "追加失敗", "ついかしっぱい")
    second = _entry(client, "追加成功", "ついかせいこう")
    fake = Mock()
    fake.list_words.return_value = []
    fake.add_word.side_effect = [OSError("failed"), "remote-2"]
    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync", json={"dictionary_entry_ids": [first, second]}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["errors"] == 1
    assert data["added"] == 1
    failed = next(item for item in data["details"] if item["dictionary_entry_id"] == first)
    assert failed["status"] == "error"
    assert failed["reason"] == "aivis_api_failed"
    assert fake.add_word.call_count == 2


def test_sync_continues_after_individual_update_failure(client):
    first = _entry(client, "更新失敗", "こうしんしっぱい")
    second = _entry(client, "更新成功", "こうしんせいこう")
    fake = Mock()
    fake.list_words.return_value = [
        {"uuid": "remote-1", "surface": "更新失敗", "pronunciation": "きゅうしん"},
        {"uuid": "remote-2", "surface": "更新成功", "pronunciation": "きゅうせい"},
    ]
    fake.update_word.side_effect = [OSError("failed"), None]
    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [first, second], "overwrite_confirmed": True},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["errors"] == 1
    assert data["updated"] == 1
    failed = next(item for item in data["details"] if item["dictionary_entry_id"] == first)
    assert failed["status"] == "error"
    assert failed["reason"] == "aivis_api_failed"
    assert fake.update_word.call_count == 2


def test_sync_dry_run_does_not_call_add_word(client):
    entry_id = _entry(client, "新規語", "しんきご")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [entry_id], "dry_run": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["added"] == 0
    assert data["updated"] == 0
    fake.add_word.assert_not_called()


def test_sync_dry_run_still_reports_confirmation_required(client):
    entry_id = _entry(client, "既存語", "きご")
    fake = Mock()
    fake.list_words.return_value = [{"uuid": "remote-1", "surface": "既存語", "pronunciation": "きぞんご"}]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [entry_id], "dry_run": True},
        )

    data = response.json()
    assert response.status_code == 200
    assert any(d["status"] == "confirmation_required" for d in data["details"])
    fake.update_word.assert_not_called()


def test_sync_dry_run_mixed_selection_no_side_effects(client):
    new_id = _entry(client, "新規語", "しんきご")
    existing_id = _entry(client, "既存語", "きご")
    fake = Mock()
    fake.list_words.return_value = [{"uuid": "remote-1", "surface": "既存語", "pronunciation": "きぞんご"}]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [new_id, existing_id], "dry_run": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["added"] == 0
    assert data["updated"] == 0
    fake.add_word.assert_not_called()
    fake.update_word.assert_not_called()


def test_sync_sends_comma_surface_as_is_and_lets_client_normalize(client):
    entry_id = _entry(client, "1,000万人", "いっせんまんにん")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    data = response.json()
    assert response.status_code == 200
    assert data["added"] == 1
    assert data["details"][0]["surface"] == "1,000万人"
    fake.add_word.assert_called_once_with("1,000万人", "いっせんまんにん")


def test_sync_detects_existing_entry_across_comma_and_width_differences(client):
    entry_id = _entry(client, "1,000万人", "いっせんまんにん")
    fake = Mock()
    # AIVIS Engineは半角登録済みの表記を全角で返す（Stage1調査で確認済み）。
    fake.list_words.return_value = [{"uuid": "remote-1", "surface": "１０００万人", "pronunciation": "いっせんまんにん"}]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    data = response.json()
    assert response.status_code == 200
    assert data["added"] == 0
    assert data["updated"] == 0
    # 正規化キーで既存項目を検出できたため「新規」ではなく確認要求として扱われる。
    assert data["details"][0]["status"] == "confirmation_required"
    assert data["details"][0]["reason"] == "remote_exists"
    fake.add_word.assert_not_called()
    fake.update_word.assert_not_called()


def test_sync_does_not_repeat_registration_on_resync(client):
    entry_id = _entry(client, "1000万人", "いっせんまんにん")
    fake = Mock()
    fake.list_words.return_value = [{"uuid": "remote-1", "surface": "１０００万人", "pronunciation": "いっせんまんにん"}]

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync",
            json={"dictionary_entry_ids": [entry_id], "overwrite_confirmed": True},
        )

    data = response.json()
    assert response.status_code == 200
    assert data["added"] == 0
    assert data["updated"] == 0
    assert data["details"][0]["reason"] == "same_reading"
    fake.add_word.assert_not_called()
    fake.update_word.assert_not_called()


def test_sync_skips_entries_that_collide_after_normalization(client):
    comma_id = _entry(client, "1,000万人", "いっせんまんにん")
    plain_id = _entry(client, "1000万人", "いっせんまんにん")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post(
            "/admin/user_dict_sync", json={"dictionary_entry_ids": [comma_id, plain_id]}
        )

    data = response.json()
    assert response.status_code == 200
    assert data["added"] == 0
    assert data["updated"] == 0
    reasons = {item["dictionary_entry_id"]: item["reason"] for item in data["details"]}
    assert reasons[comma_id] == "normalized_surface_conflict"
    assert reasons[plain_id] == "normalized_surface_conflict"
    fake.add_word.assert_not_called()
    fake.update_word.assert_not_called()


def test_sync_skips_non_thousands_comma_as_unsupported(client):
    entry_id = _entry(client, "A,B", "えーびー")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    data = response.json()
    assert response.status_code == 200
    assert data["added"] == 0
    assert data["details"][0]["status"] == "skipped"
    assert data["details"][0]["reason"] == "unsupported_comma"
    assert data["details"][0]["surface"] == "A,B"
    fake.add_word.assert_not_called()


def test_sync_skips_non_thousands_comma_like_two_digit_group(client):
    entry_id = _entry(client, "1,23", "いちにさん")
    fake = Mock()
    fake.list_words.return_value = []

    with patch("app.api.dictionary_sync.AivisUserDictClient", return_value=fake):
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    data = response.json()
    assert response.status_code == 200
    assert data["details"][0]["status"] == "skipped"
    assert data["details"][0]["reason"] == "unsupported_comma"
    fake.add_word.assert_not_called()


def test_sync_unsupported_comma_entry_does_not_call_aivis(client):
    entry_id = _entry(client, "1,23", "いちにさん")
    with patch("app.api.dictionary_sync.AivisUserDictClient") as aivis_client:
        response = client.post("/admin/user_dict_sync", json={"dictionary_entry_ids": [entry_id]})

    assert response.status_code == 200
    aivis_client.assert_not_called()


def test_sync_requires_admin(client):
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).post("/admin/user_dict_sync", json={"dictionary_entry_ids": [1]})
    assert response.status_code == 401
