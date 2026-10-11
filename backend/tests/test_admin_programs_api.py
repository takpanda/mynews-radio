from fastapi.testclient import TestClient

from app.db.connection import get_db_connection


def _program_payload(**changes):
    value = {
        "id": "custom-radio",
        "name": "カスタム番組",
        "kind": "radio",
        "cast": [{"key": "host", "name": "司会", "role": "MC"}],
        "segments": [
            {"id": "intro", "kind": "intro", "order": 0, "min_lines": 1,
             "max_lines": 2, "speaker_keys": ["host"]}
        ],
        "options": {"style": None, "mc_gender": None, "narrative_arc": False,
                    "review_mode": "on_failure"},
        "is_active": True,
    }
    value.update(changes)
    return value


def test_program_and_mc_crud_and_inactive_filters(client):
    mc = {
        "id": "custom-mc", "name": "MC", "role": "司会",
        "persona": "落ち着いて簡潔に話す。",
        "voice_fishs2pro": None, "voice_aivispeech": None,
        "voice_voicevox": None, "is_active": True,
    }
    created_mc = client.post("/admin/mcs", json=mc)
    assert created_mc.status_code == 201
    assert created_mc.json()["voice_voicevox"] is None
    assert created_mc.json()["persona"] == "落ち着いて簡潔に話す。"
    assert client.get("/admin/mcs/custom-mc").json()["voice_aivispeech"] is None
    assert client.get("/admin/mcs/custom-mc").json()["persona"] == "落ち着いて簡潔に話す。"

    updated_mc = client.put("/admin/mcs/custom-mc", json={**mc, "persona": "率直で親しみやすい。"})
    assert updated_mc.status_code == 200
    assert updated_mc.json()["persona"] == "率直で親しみやすい。"

    created_program = client.post("/admin/programs", json=_program_payload())
    assert created_program.status_code == 201
    assert client.get("/admin/programs/custom-radio").json()["definition"]["cast"][0]["key"] == "host"

    replaced = _program_payload(name="更新済み番組", is_active=False)
    assert client.put("/admin/programs/custom-radio", json=replaced).status_code == 200
    assert client.get("/admin/programs/custom-radio").json()["is_active"] is False
    omitted_active = {**replaced, "name": "状態維持を確認"}
    omitted_active.pop("is_active")
    assert client.put("/admin/programs/custom-radio", json=omitted_active).status_code == 422
    unchanged = client.get("/admin/programs/custom-radio").json()
    assert unchanged["is_active"] is False
    assert unchanged["name"] == "更新済み番組"
    assert all(item["id"] != "custom-radio" for item in client.get("/admin/programs").json())
    assert any(item["id"] == "custom-radio" for item in client.get(
        "/admin/programs?include_inactive=true"
    ).json())

    inactive_mc = {**mc, "is_active": False}
    assert client.put("/admin/mcs/custom-mc", json=inactive_mc).status_code == 200
    assert client.get("/admin/mcs/custom-mc").json()["is_active"] is False
    assert all(item["id"] != "custom-mc" for item in client.get("/admin/mcs").json())
    assert any(item["id"] == "custom-mc" for item in client.get(
        "/admin/mcs?include_inactive=true"
    ).json())


def test_program_invalid_profiles_duplicate_and_missing_ids(client):
    invalid = _program_payload(cast=[{
        "key": "host", "name": "司会", "mc_id": "missing-mc",
    }])
    assert client.post("/admin/programs", json=invalid).status_code == 422

    invalid = _program_payload(kind="commentary", options={
        "style": "solo", "mc_gender": "host", "narrative_arc": True,
        "review_mode": "on_failure",
    })
    assert client.post("/admin/programs", json=invalid).status_code == 422

    invalid = _program_payload(segments=[
        {"id": f"s{i}", "kind": "news", "order": i, "min_lines": 1,
         "max_lines": 1, "speaker_keys": ["missing"]}
        for i in range(7)
    ])
    assert client.post("/admin/programs", json=invalid).status_code == 422

    valid = _program_payload()
    assert client.post("/admin/programs", json=valid).status_code == 201
    assert client.post("/admin/programs", json=valid).status_code == 409
    assert client.get("/admin/programs/not-found").status_code == 404
    assert client.put("/admin/programs/not-found", json=_program_payload(id="not-found")).status_code == 404
    assert client.put("/admin/programs/custom-radio", json={"id": "custom-radio"}).status_code == 422


def test_admin_program_api_requires_authentication():
    from app.main import app

    unauthenticated = TestClient(app)
    assert unauthenticated.get("/admin/programs").status_code == 401
    assert unauthenticated.post("/admin/mcs", json={"id": "x", "name": "x", "role": ""}).status_code == 401


def test_mc_persona_is_bounded_and_legacy_update_preserves_it(client):
    mc = {"id": "persona-mc", "name": "MC", "role": "司会", "persona": "穏やか"}
    assert client.post("/admin/mcs", json=mc).status_code == 201
    assert client.put("/admin/mcs/persona-mc", json={"id": "persona-mc", "name": "MC", "role": "司会"}).json()["persona"] == "穏やか"
    too_long = {**mc, "id": "too-long", "persona": "x" * 4001}
    assert client.post("/admin/mcs", json=too_long).status_code == 422


def test_same_mc_can_have_distinct_roles_per_program(client):
    from app.programs.serialization import load_program_profile

    assert client.post("/admin/mcs", json={
        "id": "shared-mc", "name": "共通MC", "role": "MC", "persona": "PERSONA",
    }).status_code == 201
    for program_id, role in (("program-a", "技術解説"), ("program-b", "生活者目線")):
        payload = _program_payload(
            id=program_id,
            cast=[{"key": "host", "name": "共通MC", "role": role, "mc_id": "shared-mc"}],
            segments=[{"id": "intro", "kind": "intro", "order": 0,
                       "min_lines": 1, "max_lines": 2, "speaker_keys": ["host"]}],
        )
        assert client.post("/admin/programs", json=payload).status_code == 201
    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        role_a = load_program_profile(conn, "program-a").cast[0].role
        role_b = load_program_profile(conn, "program-b").cast[0].role
    assert role_a == "技術解説"
    assert role_b == "生活者目線"
    assert load_persona(client, "shared-mc") == "PERSONA"


def load_persona(client, mc_id):
    return client.get(f"/admin/mcs/{mc_id}").json()["persona"]


def test_program_mutations_are_audited(client):
    client.post("/admin/programs", json=_program_payload())
    client.put("/admin/programs/custom-radio", json=_program_payload(is_active=False))
    client.post("/admin/mcs", json={"id": "audit-mc", "name": "MC", "role": ""})
    client.put("/admin/mcs/audit-mc", json={
        "id": "audit-mc", "name": "MC", "role": "", "is_active": False,
    })
    with get_db_connection() as conn:
        actions = [row[0] for row in conn.execute(
            "SELECT operation FROM audit_logs WHERE operation LIKE 'admin_%' ORDER BY id"
        ).fetchall()]
    assert actions == [
        "admin_program_create", "admin_program_update", "admin_mc_create", "admin_mc_update",
    ]
