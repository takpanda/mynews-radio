import json
import sqlite3

from app.db.migration import migrate_program_profiles
from app.programs.profiles import get_default_profile, validate_program_profile
from app.programs.serialization import load_program_profile, program_profile_to_definition


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE episodes (id INTEGER PRIMARY KEY, status TEXT NOT NULL, script_text TEXT)"
    )
    return conn


def test_program_profile_migration_seeds_valid_profiles_idempotently():
    conn = _conn()
    migrate_program_profiles(conn)
    rows = conn.execute("SELECT id, name FROM programs ORDER BY id").fetchall()

    assert [(row["id"], row["name"]) for row in rows] == [
        ("commentary_dialogue", "解説 dialogue"),
        ("commentary_solo", "解説 solo"),
        ("radio_news_neighbor", "ニュースのとなり"),
        ("radio_tech_news", "テックニュース"),
    ]
    profiles = [load_program_profile(conn, row["id"]) for row in rows]
    for profile in profiles:
        validate_program_profile(profile)
    assert [member.key for member in load_program_profile(conn, "commentary_solo").cast] == ["male"]
    assert [member.key for member in get_default_profile(
        kind="commentary", style="solo", mc_gender="female"
    ).cast] == ["female"]

    before = conn.execute("SELECT id, definition FROM programs ORDER BY id").fetchall()
    migrate_program_profiles(conn)
    after = conn.execute("SELECT id, definition FROM programs ORDER BY id").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert conn.execute("SELECT COUNT(*) FROM mc_profiles").fetchone()[0] == 4


def test_program_profile_migration_preserves_existing_episode_values_and_allows_nulls():
    conn = _conn()
    conn.execute(
        "INSERT INTO episodes (id, status, script_text) VALUES (1, 'ready', 'existing script')"
    )
    migrate_program_profiles(conn)
    row = conn.execute(
        "SELECT status, script_text, program_id, program_snapshot FROM episodes WHERE id = 1"
    ).fetchone()
    assert tuple(row) == ("ready", "existing script", None, None)
    assert conn.execute("PRAGMA foreign_key_list(episodes)").fetchall()


def test_program_profile_cannot_load_when_referenced_mc_is_inactive_or_missing():
    for unavailable_mc in ("inactive", "missing"):
        conn = _conn()
        migrate_program_profiles(conn)
        if unavailable_mc == "inactive":
            conn.execute("UPDATE mc_profiles SET is_active = 0 WHERE id = 'radio_male'")
        else:
            conn.execute("DELETE FROM mc_profiles WHERE id = 'radio_male'")

        assert load_program_profile(conn, "radio_news_neighbor") is None


def test_program_profile_serialization_keeps_mc_voice_and_review_mode_fields():
    profile = get_default_profile(kind="commentary", style="solo")
    cast = profile.cast[0]
    profile = profile.__class__(
        **{
            **profile.__dict__,
            "cast": (cast.__class__(
                cast.key, cast.name, cast.role, cast.mc_id, "voice-id", 123, 4
            ),),
            "options": profile.options.__class__(
                style="solo", mc_gender="male", review_mode="always"
            ),
        }
    )
    definition = program_profile_to_definition(profile)
    round_tripped = load_from_definition(definition)
    assert round_tripped.cast[0].voice_fishs2pro == "voice-id"
    assert round_tripped.cast[0].voice_aivispeech == 123
    assert round_tripped.cast[0].voice_voicevox == 4
    assert round_tripped.options.review_mode == "always"


def load_from_definition(definition):
    from app.programs.serialization import program_profile_from_definition

    return program_profile_from_definition(json.loads(json.dumps(definition)))
