import sqlite3


def _set_thumbnail_path(episode_id, thumbnail_path):
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE episodes SET thumbnail_path = ? WHERE id = ?",
            (thumbnail_path, episode_id),
        )


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


def test_thumbnail_endpoint_rejects_invalid_episode_ids(client):
    assert client.get("/episodes/-1/thumbnail").status_code == 404
    assert client.get("/episodes/not-an-id/thumbnail").status_code == 422
    assert client.get("/episodes/../../etc/passwd").status_code in (404, 422)
