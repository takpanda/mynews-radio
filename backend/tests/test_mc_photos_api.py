from app.db.connection import get_db_connection


def _ensure_photo_column():
    with get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mc_profiles)")}
        if "photo_path" not in columns:
            conn.execute("ALTER TABLE mc_profiles ADD COLUMN photo_path TEXT")


def _create_mc(mc_id: str, photo_path: str | None = None):
    _ensure_photo_column()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO mc_profiles(id, name, role, photo_path, is_active) "
            "VALUES (?, ?, ?, ?, 0)",
            (mc_id, "MC", "司会", photo_path),
        )


def test_mc_photo_endpoint_serves_webp_without_auth_or_active_check(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PHOTOS_DIR", str(tmp_path / "mc-photos"))
    from app.config import get_settings

    get_settings.cache_clear()
    photos_dir = tmp_path / "mc-photos"
    photos_dir.mkdir()
    photo = photos_dir / "profile.webp"
    photo_bytes = b"webp-image-data"
    photo.write_bytes(photo_bytes)
    _create_mc("inactive-mc", photo.name)

    client.cookies.clear()
    response = client.get("/mcs/inactive-mc/photo")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.content == photo_bytes


def test_mc_photo_endpoint_returns_404_for_missing_mc_photo_or_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PHOTOS_DIR", str(tmp_path / "mc-photos"))
    from app.config import get_settings

    get_settings.cache_clear()
    (tmp_path / "mc-photos").mkdir()
    _create_mc("no-photo-mc")
    _create_mc("missing-file-mc", "missing.webp")

    client.cookies.clear()
    assert client.get("/mcs/unknown-mc/photo").status_code == 404
    assert client.get("/mcs/no-photo-mc/photo").status_code == 404
    assert client.get("/mcs/missing-file-mc/photo").status_code == 404


def test_mc_photo_endpoint_rejects_path_traversal_and_outside_symlink(client, tmp_path, monkeypatch):
    photos_dir = tmp_path / "mc-photos"
    photos_dir.mkdir()
    monkeypatch.setenv("MC_PHOTOS_DIR", str(photos_dir))
    from app.config import get_settings

    get_settings.cache_clear()
    outside_file = tmp_path / "private.webp"
    outside_file.write_bytes(b"private")
    (photos_dir / "linked.webp").symlink_to(outside_file)
    _create_mc("traversal-mc", "../private.webp")
    _create_mc("symlink-mc", "linked.webp")
    _create_mc("invalid-path-mc", "invalid\x00.webp")

    client.cookies.clear()
    assert client.get("/mcs/traversal-mc/photo").status_code == 404
    assert client.get("/mcs/symlink-mc/photo").status_code == 404
    assert client.get("/mcs/invalid-path-mc/photo").status_code == 404
