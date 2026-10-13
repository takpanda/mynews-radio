import sqlite3


def _set_thumbnail_path(episode_id, thumbnail_path):
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET thumbnail_path = ? WHERE id = ?",
            (thumbnail_path, episode_id),
        )


def _create_thumbnail_episode(service, tmp_path, episode_date, *, status="pending", audio=False):
    episode_id = service.create_episode(
        episode_date=episode_date,
        audio_path="episode.mp3" if audio else None,
        status=status,
    )
    episode_dir = tmp_path / "episodes" / str(episode_id)
    episode_dir.mkdir(parents=True)
    (episode_dir / "thumbnail.png").write_bytes(b"\x89PNG\r\n\x1a\nthumbnail")
    if audio:
        (episode_dir / "episode.mp3").write_bytes(b"audio")
    _set_thumbnail_path(episode_id, f"/app/data/episodes/{episode_id}/thumbnail.png")
    return episode_id, episode_dir


def test_migrate_episode_thumbnail_preserves_existing_rows():
    from app.db.migration import migrate_episode_thumbnail

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    conn.execute("INSERT INTO episodes (id, status) VALUES (1, 'completed')")

    assert migrate_episode_thumbnail(conn) is True
    assert migrate_episode_thumbnail(conn) is False
    row = conn.execute("SELECT status, thumbnail_path FROM episodes WHERE id = 1").fetchone()
    assert row == ("completed", None)


def test_thumbnail_endpoint_serves_png_and_episode_responses_include_url(client, tmp_path):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode(
        episode_date="2099-12-20", audio_path="episode.mp3", status="completed"
    )
    episode_dir = tmp_path / "episodes" / str(episode_id)
    episode_dir.mkdir(parents=True)
    (episode_dir / "episode.mp3").write_bytes(b"audio")
    png_bytes = b"\x89PNG\r\n\x1a\nthumbnail"
    (episode_dir / "thumbnail.png").write_bytes(png_bytes)
    _set_thumbnail_path(episode_id, f"/app/data/episodes/{episode_id}/thumbnail.png")

    response = client.get(f"/episodes/{episode_id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png_bytes

    listed = client.get("/episodes").json()
    episode = next(item for item in listed if item["id"] == episode_id)
    assert episode["thumbnail_url"] == f"/api/episodes/{episode_id}/thumbnail"
    detail = client.get(f"/episodes/{episode_id}").json()
    assert detail["thumbnail_url"] == f"/api/episodes/{episode_id}/thumbnail"


def test_thumbnail_endpoint_returns_404_when_path_is_null_or_file_missing(client, tmp_path):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    null_id = service.create_episode(episode_date="2099-12-21")
    missing_id = service.create_episode(episode_date="2099-12-22")
    _set_thumbnail_path(missing_id, f"/app/data/episodes/{missing_id}/thumbnail.png")
    (tmp_path / "episodes" / str(missing_id)).mkdir(parents=True)

    assert client.get(f"/episodes/{null_id}/thumbnail").status_code == 404
    assert client.get(f"/episodes/{missing_id}/thumbnail").status_code == 404
    assert client.get(f"/episodes/{null_id}").json()["thumbnail_url"] is None


def test_thumbnail_endpoint_enforces_public_and_admin_access(client, tmp_path):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    public_id, _ = _create_thumbnail_episode(
        service, tmp_path, "2099-12-23", status="completed", audio=True
    )
    private_id, _ = _create_thumbnail_episode(service, tmp_path, "2099-12-24")
    session_cookie = next(
        cookie.value for cookie in client.cookies.jar if cookie.name == "admin_session"
    )
    client.cookies.clear()

    assert client.get(f"/episodes/{public_id}/thumbnail").status_code == 200
    assert client.get(f"/episodes/{private_id}/thumbnail").status_code == 404

    client.cookies.set("admin_session", session_cookie)
    assert client.get(f"/episodes/{private_id}/thumbnail").status_code == 200


def test_thumbnail_endpoint_rejects_symlink_outside_episodes_directory(client, tmp_path):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    episode_id = service.create_episode(episode_date="2099-12-25")
    episode_dir = tmp_path / "episodes" / str(episode_id)
    episode_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.png"
    outside_file.write_bytes(b"private")
    (episode_dir / "thumbnail.png").symlink_to(outside_file)
    _set_thumbnail_path(episode_id, f"/app/data/episodes/{episode_id}/thumbnail.png")

    assert client.get(f"/episodes/{episode_id}/thumbnail").status_code == 404


def test_latest_and_source_url_apis_include_thumbnail_url(client, tmp_path):
    from app.services.episode_service import EpisodeService

    service = EpisodeService()
    latest_id, _ = _create_thumbnail_episode(
        service, tmp_path, "2099-12-26", status="completed", audio=True
    )
    latest = client.get("/episodes/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == latest_id
    assert latest.json()["thumbnail_url"] == f"/api/episodes/{latest_id}/thumbnail"

    source_url = "https://example.com/thumbnail-source"
    source_id = service.create_episode(
        episode_date="2099-12-27", type="commentary", source_url=source_url
    )
    source_dir = tmp_path / "episodes" / str(source_id)
    source_dir.mkdir(parents=True)
    (source_dir / "thumbnail.png").write_bytes(b"png")
    _set_thumbnail_path(source_id, f"/app/data/episodes/{source_id}/thumbnail.png")

    response = client.get(
        "/episodes/search/by-source-url", params={"source_url": source_url}
    )
    assert response.status_code == 200
    assert response.json()[0]["thumbnail_url"] == f"/api/episodes/{source_id}/thumbnail"


def test_thumbnail_endpoint_rejects_invalid_episode_ids(client):
    assert client.get("/episodes/-1/thumbnail").status_code == 404
    assert client.get("/episodes/not-an-id/thumbnail").status_code == 422
    assert client.get("/episodes/../../etc/passwd/thumbnail").status_code in (404, 422)
