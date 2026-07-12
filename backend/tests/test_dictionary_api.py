"""Tests for dictionary entries CRUD API with UNIQUE(surface, reading) constraint."""


class TestCreateDictionaryEntry:
    """POST /admin/dictionary のテスト"""

    def test_create_entry(self, client):
        resp = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["word"] == "テスト"
        assert data["reading"] == "てすと"
        assert data["status"] == "active"

    def test_create_duplicate_surface_reading(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        resp = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Dictionary entry already exists"

    def test_create_same_word_different_reading(self, client):
        """同じ word で reading が異なる場合は別エントリとして登録できる"""
        resp1 = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "とうきょう", "category": "general"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "トウキョウ", "category": "general"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["word"] == "東京"
        assert resp2.json()["reading"] == "トウキョウ"


class TestListDictionaryEntries:
    """GET /admin/dictionary のテスト"""

    def test_list_empty(self, client):
        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_entries(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        )
        client.post(
            "/admin/dictionary",
            json={"word": "東京", "reading": "とうきょう", "category": "place"},
        )
        resp = client.get("/admin/dictionary")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        words = {e["word"] for e in data}
        assert words == {"テスト", "東京"}


class TestUpdateDictionaryEntry:
    """PUT /admin/dictionary/{id} のテスト"""

    def test_update_entry(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.put(
            f"/admin/dictionary/{created['id']}",
            json={"word": "更新", "reading": "こうしん", "category": "general"},
        )
        assert resp.status_code == 200
        assert resp.json()["word"] == "更新"
        assert resp.json()["reading"] == "こうしん"

    def test_update_to_existing_word_reading(self, client):
        client.post(
            "/admin/dictionary",
            json={"word": "既存", "reading": "きそん", "category": "general"},
        )
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.put(
            f"/admin/dictionary/{created['id']}",
            json={"word": "既存", "reading": "きそん", "category": "general"},
        )
        assert resp.status_code == 409

    def test_update_404(self, client):
        resp = client.put(
            "/admin/dictionary/99999",
            json={"word": "なし", "reading": "なし", "category": "general"},
        )
        assert resp.status_code == 404


class TestGetDictionaryEntry:
    """GET /admin/dictionary/{id} のテスト"""

    def test_get_entry(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()

        resp = client.get(f"/admin/dictionary/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["word"] == "テスト"

    def test_get_404(self, client):
        resp = client.get("/admin/dictionary/99999")
        assert resp.status_code == 404


class TestDictionaryEntryStatus:
    """PATCH /admin/dictionary/{id}/status のテスト"""

    def test_toggle_status(self, client):
        created = client.post(
            "/admin/dictionary",
            json={"word": "テスト", "reading": "てすと", "category": "general"},
        ).json()
        assert created["status"] == "active"

        resp = client.patch(
            f"/admin/dictionary/{created['id']}/status",
            json={"status": "inactive"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

        resp = client.patch(
            f"/admin/dictionary/{created['id']}/status",
            json={"status": "active"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
