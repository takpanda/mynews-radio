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


def _image_bytes(format="PNG", size=(32, 24), exif=None):
    image = Image.new("RGB", size, "navy")
    data = io.BytesIO()
    save_options = {"exif": exif} if exif is not None else {}
    image.save(data, format=format, **save_options)
    return data.getvalue()


def _corrupt_png_idat_crc(data):
    corrupted = bytearray(data)
    offset = 8
    while offset < len(corrupted):
        chunk_length = int.from_bytes(corrupted[offset:offset + 4], "big")
        chunk_type = corrupted[offset + 4:offset + 8]
        crc_offset = offset + 8 + chunk_length
        if chunk_type == b"IDAT":
            corrupted[crc_offset] ^= 1
            return bytes(corrupted)
        offset = crc_offset + 4
    raise AssertionError("PNG has no IDAT chunk")


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


def test_upload_rejects_png_with_corrupted_idat_crc(client):
    _create_mc(client)
    broken_png = _corrupt_png_idat_crc(_image_bytes())
    response = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("broken-crc.png", broken_png, "image/png")},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("size,expected", [
    ((1024, 256), (512, 128)),
    ((256, 1024), (128, 512)),
])
def test_upload_resizes_wide_and_tall_images(client, tmp_path, monkeypatch, size, expected):
    monkeypatch.setenv("MC_PHOTOS_DIR", str(tmp_path / "mc-photos"))
    from app.config import get_settings
    get_settings.cache_clear()
    _create_mc(client)

    response = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("large.png", _image_bytes(size=size), "image/png")},
    )
    assert response.status_code == 200
    saved_file = next((tmp_path / "mc-photos").glob("*.webp"))
    with Image.open(saved_file) as saved:
        assert saved.size == expected
        assert max(saved.size) == 512


def test_upload_removes_exif_metadata(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PHOTOS_DIR", str(tmp_path / "mc-photos"))
    from app.config import get_settings
    get_settings.cache_clear()
    _create_mc(client)
    exif = Image.Exif()
    exif[0x010E] = "Private camera metadata"

    response = client.post(
        "/admin/mcs/photo-mc/photo",
        files={"file": ("with-exif.jpg", _image_bytes("JPEG", (800, 400), exif), "image/jpeg")},
    )
    assert response.status_code == 200
    saved_file = next((tmp_path / "mc-photos").glob("*.webp"))
    with Image.open(saved_file) as saved:
        assert saved.size == (512, 256)
        assert not saved.getexif()


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
