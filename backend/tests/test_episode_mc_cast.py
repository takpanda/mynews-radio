import json


def _ensure_photo_column():
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mc_profiles)")}
        if "photo_path" not in columns:
            conn.execute("ALTER TABLE mc_profiles ADD COLUMN photo_path TEXT")


def _create_mc(mc_id: str, name: str, role: str, photo_path: str | None = None):
    from app.db.connection import get_db_connection

    _ensure_photo_column()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO mc_profiles(id, name, role, photo_path, is_active) VALUES (?, ?, ?, ?, 1)",
            (mc_id, name, role, photo_path),
        )


def _create_episode_with_snapshot(program_snapshot):
    from app.db.connection import get_db_connection
    from app.services.episode_service import EpisodeService

    episode_id = EpisodeService().create_episode("2099-12-26")
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET program_snapshot = ? WHERE id = ?",
            (program_snapshot, episode_id),
        )
    return episode_id


def _use_photos_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    photos_dir = tmp_path / "mc-photos"
    photos_dir.mkdir()
    monkeypatch.setenv("MC_PHOTOS_DIR", str(photos_dir))
    get_settings.cache_clear()
    return photos_dir


def test_detail_returns_mc_cast_with_photo_urls(client, tmp_path, monkeypatch):
    photos_dir = _use_photos_dir(tmp_path, monkeypatch)
    (photos_dir / "3f9c0a1b2c3d.webp").write_bytes(b"webp")
    _create_mc("radio_male", "田村", "進行役", "3f9c0a1b2c3d.webp")
    _create_mc("radio_female", "山口", "聞き手")
    snapshot = {
        "id": "radio_news",
        "name": "ニュースラジオ",
        "cast": [
            {"key": "male", "name": "田村", "role": "進行役", "mc_id": "radio_male", "persona": "x"},
            {"key": "female", "name": "山口", "role": "聞き手", "mc_id": "radio_female", "persona": "y"},
        ],
    }
    episode_id = _create_episode_with_snapshot(json.dumps(snapshot, ensure_ascii=False))

    response = client.get(f"/episodes/{episode_id}")

    assert response.status_code == 200
    assert response.json()["mc_cast"] == [
        {
            "key": "male",
            "mc_id": "radio_male",
            "name": "田村",
            "role": "進行役",
            "photo_url": "/api/mcs/radio_male/photo?v=3f9c0a1b",
        },
        {
            "key": "female",
            "mc_id": "radio_female",
            "name": "山口",
            "role": "聞き手",
            "photo_url": None,
        },
    ]


def test_mc_cast_is_empty_for_legacy_or_broken_snapshot(client, tmp_path, monkeypatch):
    _use_photos_dir(tmp_path, monkeypatch)
    _create_mc("radio_male", "田村", "進行役")
    snapshots = [
        None,
        "",
        "{broken json",
        "[]",
        json.dumps({"id": "radio_news"}),
        json.dumps({"cast": "radio_male"}),
    ]

    for snapshot in snapshots:
        episode_id = _create_episode_with_snapshot(snapshot)

        response = client.get(f"/episodes/{episode_id}")

        assert response.status_code == 200, snapshot
        assert response.json()["mc_cast"] == [], snapshot


def test_mc_cast_skips_members_without_usable_mc_reference(client, tmp_path, monkeypatch):
    _use_photos_dir(tmp_path, monkeypatch)
    _create_mc("radio_male", "田村", "進行役")
    snapshot = {
        "cast": [
            "radio_male",
            {"key": "male", "mc_id": None, "name": "田村"},
            {"key": "male", "name": "田村"},
            {"key": "female", "mc_id": "deleted_mc", "name": "山口"},
            {"key": "guest", "mc_id": "radio_male", "name": "田村"},
            {"mc_id": "radio_male", "name": "田村"},
        ],
    }
    episode_id = _create_episode_with_snapshot(json.dumps(snapshot, ensure_ascii=False))

    response = client.get(f"/episodes/{episode_id}")

    assert response.status_code == 200
    assert response.json()["mc_cast"] == [
        {
            "key": "guest",
            "mc_id": "radio_male",
            "name": "田村",
            "role": "進行役",
            "photo_url": None,
        },
    ]


def test_mc_cast_photo_url_is_none_when_photo_path_escapes_photos_dir(client, tmp_path, monkeypatch):
    _use_photos_dir(tmp_path, monkeypatch)
    (tmp_path / "private.webp").write_bytes(b"private")
    _create_mc("traversal-mc", "MC", "司会", "../private.webp")
    snapshot = {"cast": [{"key": "male", "mc_id": "traversal-mc"}]}
    episode_id = _create_episode_with_snapshot(json.dumps(snapshot))

    response = client.get(f"/episodes/{episode_id}")

    assert response.status_code == 200
    assert response.json()["mc_cast"][0]["photo_url"] is None
