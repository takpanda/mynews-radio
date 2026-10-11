"""JSON serialization for database-backed program definitions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.programs.profiles import (
    COMMENTARY_FEMALE_PERSONA,
    COMMENTARY_MALE_PERSONA,
    ProgramCastMember,
    ProgramOptions,
    ProgramProfile,
    ProgramSegment,
    RADIO_FEMALE_PERSONA,
    RADIO_FEMALE_ROLE,
    RADIO_MALE_PERSONA,
    RADIO_MALE_ROLE,
    validate_program_profile,
)


def program_profile_to_definition(profile: ProgramProfile) -> dict[str, Any]:
    """Return the stable JSON-compatible definition stored in ``programs``."""
    validate_program_profile(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "kind": profile.kind,
        "cast": [
            {
                "key": member.key,
                "name": member.name,
                "role": member.role,
                "mc_id": member.mc_id,
                "persona": member.persona,
                "voice_fishs2pro": member.voice_fishs2pro,
                "voice_aivispeech": member.voice_aivispeech,
                "voice_voicevox": member.voice_voicevox,
            }
            for member in profile.cast
        ],
        "segments": [
            {
                "id": segment.id,
                "kind": segment.kind,
                "order": segment.order,
                "min_lines": segment.min_lines,
                "max_lines": segment.max_lines,
                "speaker_keys": list(segment.speaker_keys),
                "label": segment.label,
            }
            for segment in profile.segments
        ],
        "options": {
            "style": profile.options.style,
            "mc_gender": profile.options.mc_gender,
            "narrative_arc": profile.options.narrative_arc,
            "review_mode": profile.options.review_mode,
        },
    }


def program_profile_from_definition(definition: dict[str, Any]) -> ProgramProfile:
    """Parse and validate a stored program definition."""
    options = definition.get("options") or {}

    legacy_mc_data = {
        "radio_male": (RADIO_MALE_PERSONA, "メインMC", RADIO_MALE_ROLE),
        "radio_female": (RADIO_FEMALE_PERSONA, "パートナーMC", RADIO_FEMALE_ROLE),
        "commentary_male": (COMMENTARY_MALE_PERSONA, None, None),
        "commentary_female": (COMMENTARY_FEMALE_PERSONA, None, None),
    }

    def cast_member(item: dict[str, Any]) -> ProgramCastMember:
        values = dict(item)
        legacy = legacy_mc_data.get(values.get("mc_id"))
        if "persona" not in values and legacy is not None:
            values["persona"] = legacy[0]
        if legacy is not None and values.get("role") == legacy[1] and legacy[2] is not None:
            values["role"] = legacy[2]
        values["persona"] = values.get("persona") or ""
        return ProgramCastMember(**values)

    profile = ProgramProfile(
        id=definition["id"],
        name=definition["name"],
        kind=definition["kind"],
        cast=tuple(cast_member(item) for item in definition["cast"]),
        segments=tuple(
            ProgramSegment(
                id=item["id"],
                kind=item["kind"],
                order=item["order"],
                min_lines=item["min_lines"],
                max_lines=item["max_lines"],
                speaker_keys=tuple(item.get("speaker_keys", ())),
                label=item.get("label", ""),
            )
            for item in definition["segments"]
        ),
        options=ProgramOptions(
            style=options.get("style"),
            mc_gender=options.get("mc_gender"),
            narrative_arc=options.get("narrative_arc", False),
            review_mode=options.get("review_mode", "on_failure"),
        ),
    )
    validate_program_profile(profile)
    return profile


def load_program_profile(conn, program_id: str) -> ProgramProfile | None:
    """Read an active program definition from SQLite and validate its profile."""
    import json

    row = conn.execute(
        "SELECT definition FROM programs WHERE id = ? AND is_active = 1",
        (program_id,),
    ).fetchone()
    if row is None:
        return None
    raw_definition = row["definition"] if hasattr(row, "keys") else row[0]
    profile = program_profile_from_definition(json.loads(raw_definition))
    mc_rows = conn.execute(
        "SELECT id, persona, voice_fishs2pro, voice_aivispeech, voice_voicevox "
        "FROM mc_profiles WHERE is_active = 1"
    ).fetchall()
    mc_by_id = {
        (row["id"] if hasattr(row, "keys") else row[0]): row
        for row in mc_rows
    }
    cast = []
    for member in profile.cast:
        mc = mc_by_id.get(member.mc_id)
        if mc is None:
            if member.mc_id is not None:
                return None
            cast.append(member)
            continue
        values = {
            "persona": mc["persona"] if hasattr(mc, "keys") else mc[1],
            "voice_fishs2pro": mc["voice_fishs2pro"] if hasattr(mc, "keys") else mc[2],
            "voice_aivispeech": mc["voice_aivispeech"] if hasattr(mc, "keys") else mc[3],
            "voice_voicevox": mc["voice_voicevox"] if hasattr(mc, "keys") else mc[4],
        }
        cast.append(replace(member, **values))
    profile = replace(profile, cast=tuple(cast))
    validate_program_profile(profile)
    return profile
