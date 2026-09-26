"""番組・MCプロファイルの管理API。"""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_admin_with_token
from app.audit import hash_input, insert_audit_log
from app.db.connection import get_db_connection
from app.programs.profiles import (
    ProgramCastMember,
    ProgramOptions,
    ProgramProfile,
    ProgramSegment,
    ProfileValidationError,
    validate_program_profile,
)
from app.programs.serialization import program_profile_to_definition


router = APIRouter(prefix="/admin", tags=["admin-programs"])
AdminContext = Annotated[tuple[int, str], Depends(require_admin_with_token)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProgramCastInput(StrictModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(max_length=200)
    role: str = Field(default="", max_length=200)
    mc_id: str | None = Field(default=None, max_length=100)
    voice_fishs2pro: str | None = Field(default=None, max_length=200)
    voice_aivispeech: int | None = None
    voice_voicevox: int | None = None


class ProgramSegmentInput(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=50)
    order: int = Field(ge=0)
    min_lines: int = Field(ge=0)
    max_lines: int = Field(ge=0)
    speaker_keys: list[str] = Field(default_factory=list)
    label: str = Field(default="", max_length=200)


class ProgramOptionsInput(StrictModel):
    style: str | None = None
    mc_gender: str | None = None
    narrative_arc: bool = False
    review_mode: str = "on_failure"


class ProgramInput(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["radio", "commentary"]
    cast: list[ProgramCastInput]
    segments: list[ProgramSegmentInput]
    options: ProgramOptionsInput
    is_active: bool = True


class McInput(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(max_length=200)
    role: str = Field(max_length=200)
    voice_fishs2pro: str | None = Field(default=None, max_length=200)
    voice_aivispeech: int | None = None
    voice_voicevox: int | None = None
    is_active: bool = True


def _profile(body: ProgramInput) -> ProgramProfile:
    profile = ProgramProfile(
        id=body.id,
        name=body.name,
        kind=body.kind,
        cast=tuple(ProgramCastMember(**item.model_dump()) for item in body.cast),
        segments=tuple(
            ProgramSegment(**{**item.model_dump(), "speaker_keys": tuple(item.speaker_keys)})
            for item in body.segments
        ),
        options=ProgramOptions(**body.options.model_dump()),
    )
    try:
        validate_program_profile(profile)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile


def _program_row(row) -> dict:
    definition = json.loads(row["definition"])
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "definition": definition,
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _mc_row(row) -> dict:
    value = dict(row)
    value["is_active"] = bool(value["is_active"])
    return value


def _audit(conn, operation: str, actor: int, payload: dict) -> None:
    # API_KEY も既存管理APIの認証手段として受け入れるが、匿名のサービス主体には
    # admin_users の外部キーを付けられないため、actor は NULL で記録する。
    insert_audit_log(
        conn,
        operation=operation,
        actor_user_id=actor if actor > 0 else None,
        result="success",
        input_hash=hash_input(payload),
    )


def _validate_mc_references(conn, profile: ProgramProfile) -> None:
    mc_ids = {member.mc_id for member in profile.cast if member.mc_id is not None}
    for mc_id in mc_ids:
        row = conn.execute(
            "SELECT is_active FROM mc_profiles WHERE id = ?", (mc_id,)
        ).fetchone()
        if row is None or not row["is_active"]:
            raise HTTPException(status_code=422, detail=f"Unknown or inactive MC: {mc_id}")


@router.get("/programs")
def list_programs(
    _: AdminContext,
    include_inactive: bool = Query(default=False),
) -> list[dict]:
    query = "SELECT * FROM programs"
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY id"
    with get_db_connection() as conn:
        return [_program_row(row) for row in conn.execute(query).fetchall()]


@router.post("/programs", status_code=201)
def create_program(body: ProgramInput, admin: AdminContext) -> dict:
    profile = _profile(body)
    definition = program_profile_to_definition(profile)
    encoded = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
    with get_db_connection() as conn:
        _validate_mc_references(conn, profile)
        if conn.execute("SELECT 1 FROM programs WHERE id = ?", (body.id,)).fetchone():
            raise HTTPException(status_code=409, detail="Program slug already exists")
        conn.execute(
            "INSERT INTO programs(id, name, kind, definition, is_active) VALUES (?, ?, ?, ?, ?)",
            (body.id, body.name, body.kind, encoded, int(body.is_active)),
        )
        _audit(conn, "admin_program_create", admin[0], body.model_dump())
        row = conn.execute("SELECT * FROM programs WHERE id = ?", (body.id,)).fetchone()
        return _program_row(row)


@router.get("/programs/{program_id}")
def get_program(program_id: str, _: AdminContext) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Program not found")
        return _program_row(row)


@router.put("/programs/{program_id}")
def replace_program(program_id: str, body: ProgramInput, admin: AdminContext) -> dict:
    profile = _profile(body)
    if body.id != program_id:
        raise HTTPException(status_code=422, detail="Program id must match path id")
    definition = program_profile_to_definition(profile)
    encoded = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM programs WHERE id = ?", (program_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Program not found")
        _validate_mc_references(conn, profile)
        conn.execute(
            "UPDATE programs SET name = ?, kind = ?, definition = ?, is_active = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.name, body.kind, encoded, int(body.is_active), program_id),
        )
        _audit(conn, "admin_program_update", admin[0], body.model_dump())
        return _program_row(conn.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone())


@router.get("/mcs")
def list_mcs(
    _: AdminContext,
    include_inactive: bool = Query(default=False),
) -> list[dict]:
    query = "SELECT * FROM mc_profiles"
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY id"
    with get_db_connection() as conn:
        return [_mc_row(row) for row in conn.execute(query).fetchall()]


@router.post("/mcs", status_code=201)
def create_mc(body: McInput, admin: AdminContext) -> dict:
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM mc_profiles WHERE id = ?", (body.id,)).fetchone():
            raise HTTPException(status_code=409, detail="MC id already exists")
        conn.execute(
            "INSERT INTO mc_profiles(id, name, role, voice_fishs2pro, voice_aivispeech, voice_voicevox, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (body.id, body.name, body.role, body.voice_fishs2pro, body.voice_aivispeech,
             body.voice_voicevox, int(body.is_active)),
        )
        _audit(conn, "admin_mc_create", admin[0], body.model_dump())
        return _mc_row(conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (body.id,)).fetchone())


@router.get("/mcs/{mc_id}")
def get_mc(mc_id: str, _: AdminContext) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="MC not found")
        return _mc_row(row)


@router.put("/mcs/{mc_id}")
def replace_mc(mc_id: str, body: McInput, admin: AdminContext) -> dict:
    if body.id != mc_id:
        raise HTTPException(status_code=422, detail="MC id must match path id")
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="MC not found")
        conn.execute(
            "UPDATE mc_profiles SET name = ?, role = ?, voice_fishs2pro = ?, voice_aivispeech = ?, "
            "voice_voicevox = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.name, body.role, body.voice_fishs2pro, body.voice_aivispeech,
             body.voice_voicevox, int(body.is_active), mc_id),
        )
        _audit(conn, "admin_mc_update", admin[0], body.model_dump())
        return _mc_row(conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone())
