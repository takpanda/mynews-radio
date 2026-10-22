import io

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.db.connection import get_db_connection
from app.db.migration import migrate_mc_profile_photo, migrate_program_profiles


@pytest.fixture(autouse=True)
def _ensure_profile_schema(test_env):
    # The application module may already be imported by another test module;
    # apply startup migrations to this test's fresh database explicitly.
    with get_db_connection() as conn:
        migrate_program_profiles(conn)
        migrate_mc_profile_photo(conn)


def _image_bytes(format="PNG"):
    image = Image.new("RGB", (32, 24), "navy")
    data = io.BytesIO()
    image.save(data, format=format)
    return data.getvalue()


def _create_mc(client, mc_id="photo-mc"):
    response = client.post("/admin/mcs", json={"id": mc_id, "name": "写真MC", "role": "司会"})
    assert response.status_code == 201
    return response


def test_upload_replaces_photo_and_delete_is_idempotent(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PHOTOS_DIR", str(tmp_path / "mc-photos"))
    from app.config import get_settings
    get_settings.cache_clear()
    _create_mc(client)

    uploaded = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("photo.png", _image_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    first = uploaded.json()
    assert first["photo_url"].startswith("/api/mcs/photo-mc/photo?v=")
    assert "photo_path" not in first
    first_file = next((tmp_path / "mc-photos").glob("*.webp"))
    with Image.open(first_file) as saved:
        assert saved.format == "WEBP"
        assert saved.size == (32, 24)
        assert not saved.getexif()

    replaced = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("photo.png", _image_bytes("JPEG"), "image/jpeg")},
    )
    assert replaced.status_code == 200
    second_file = next((tmp_path / "mc-photos").glob("*.webp"))
    assert second_file != first_file
    assert not first_file.exists()

    deleted = client.delete("/admin/mcs/photo-mc/photo")
    assert deleted.status_code == 200
    assert deleted.json()["photo_url"] is None
    assert not second_file.exists()
    assert client.delete("/admin/mcs/photo-mc/photo").status_code == 200
    with get_db_connection() as conn:
        actions = [row[0] for row in conn.execute(
            "SELECT operation FROM audit_logs WHERE operation LIKE 'admin_mc_photo_%' ORDER BY id"
        )]
    assert actions == ["admin_mc_photo_update", "admin_mc_photo_update",
                       "admin_mc_photo_delete", "admin_mc_photo_delete"]


@pytest.mark.parametrize("name,data,mime", [
    ("photo.gif", _image_bytes("GIF"), "image/gif"),
    ("photo.txt", b"plain text", "text/plain"),
    ("broken.png", b"not an image", "image/png"),
])
def test_upload_rejects_unsupported_or_invalid_images(client, name, data, mime):
    _create_mc(client)
    response = client.post("/admin/mcs/photo-mc/photo", files={"file": (name, data, mime)})
    assert response.status_code == 422


def test_upload_rejects_oversize_and_missing_mc(client):
    _create_mc(client)
    large = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert large.status_code == 413
    missing = client.post(
        "/admin/mcs/missing/photo", files={"file": ("photo.png", _image_bytes(), "image/png")}
    )
    assert missing.status_code == 404


def test_photo_management_requires_admin_authentication():
    from app.main import app

    unauthenticated = TestClient(app)
    response = unauthenticated.post(
        "/admin/mcs/missing/photo", files={"file": ("photo.png", _image_bytes(), "image/png")}
    )
    assert response.status_code == 401
