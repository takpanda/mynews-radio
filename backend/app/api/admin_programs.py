"""番組・MCプロファイルの管理API。"""

import io
import json
import logging
import os
import uuid
from typing import Annotated, Literal
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_admin_with_token
from app.audit import hash_input, insert_audit_log
from app.config import get_settings
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
logger = logging.getLogger(__name__)
MC_PHOTO_MAX_BYTES = 5 * 1024 * 1024
MC_PHOTO_MAX_PIXELS = 40_000_000
MC_PHOTO_MAX_DIMENSION = 512


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


class ProgramSelectionInput(StrictModel):
    news_source: Literal[
        "hatena_bookmark", "hatena_hotentry_all", "yahoo_news", "url"
    ] | None = None
    priority_themes: list[str] | None = None
    excluded_themes: list[str] | None = None
    max_articles: int | None = Field(default=None, ge=1, le=50)
    min_importance_score: int | None = Field(default=None, ge=1, le=5)
    duration_preset: Literal["short", "normal", "long"] | None = None


class ProgramFields(ProgramSelectionInput):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["radio", "commentary"]
    cast: list[ProgramCastInput]
    segments: list[ProgramSegmentInput]
    options: ProgramOptionsInput


class ProgramInput(ProgramFields):
    is_active: bool = True


class ProgramReplaceInput(ProgramFields):
    is_active: bool


class McInput(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(max_length=200)
    role: str = Field(max_length=200)
    persona: str | None = Field(default=None, max_length=4000)
    voice_fishs2pro: str | None = Field(default=None, max_length=200)
    voice_aivispeech: int | None = None
    voice_voicevox: int | None = None
    is_active: bool = True


def _profile(body: ProgramFields) -> ProgramProfile:
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
        news_source=body.news_source,
        priority_themes=tuple(body.priority_themes) if body.priority_themes is not None else None,
        excluded_themes=tuple(body.excluded_themes) if body.excluded_themes is not None else None,
        max_articles=body.max_articles,
        min_importance_score=body.min_importance_score,
        duration_preset=body.duration_preset,
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
    photo_path = value.pop("photo_path", None)
    photo_url = None
    if photo_path:
        safe_name = os.path.basename(photo_path)
        photo_file = Path(get_settings().mc_photos_dir, safe_name)
        try:
            if photo_file.is_file() and photo_file.resolve().is_relative_to(
                Path(get_settings().mc_photos_dir).resolve()
            ):
                photo_url = f"/api/mcs/{quote(value['id'], safe='')}/photo?v={Path(safe_name).stem[:8]}"
        except (OSError, ValueError):
            logger.warning("MC photo path could not be resolved")
    value["photo_url"] = photo_url
    return value


async def _read_mc_photo(upload: UploadFile) -> bytes:
    contents = bytearray()
    while chunk := await upload.read(64 * 1024):
        contents.extend(chunk)
        if len(contents) > MC_PHOTO_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Photo exceeds 5 MB")
    if not contents:
        raise HTTPException(status_code=422, detail="Invalid image")

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image_format = image.format
            if image_format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(status_code=422, detail="Unsupported image format")
            if image.width * image.height > MC_PHOTO_MAX_PIXELS:
                raise HTTPException(status_code=422, detail="Image dimensions are too large")
            image.verify()
        with Image.open(io.BytesIO(contents)) as image:
            image.thumbnail((MC_PHOTO_MAX_DIMENSION, MC_PHOTO_MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85, method=6)
            return output.getvalue()
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(status_code=422, detail="Invalid image") from exc


def _stored_mc_photo_path(filename: str | None) -> Path | None:
    if not filename or os.path.basename(filename) != filename:
        return None
    root = Path(get_settings().mc_photos_dir).resolve()
    candidate = (root / filename).resolve()
    return candidate if candidate.is_relative_to(root) else None


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
def replace_program(program_id: str, body: ProgramReplaceInput, admin: AdminContext) -> dict:
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
            "INSERT INTO mc_profiles(id, name, role, persona, voice_fishs2pro, voice_aivispeech, voice_voicevox, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body.id, body.name, body.role, body.persona or "", body.voice_fishs2pro, body.voice_aivispeech,
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
            "UPDATE mc_profiles SET name = ?, role = ?, persona = COALESCE(?, persona), "
            "voice_fishs2pro = ?, voice_aivispeech = ?, "
            "voice_voicevox = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.name, body.role, body.persona, body.voice_fishs2pro, body.voice_aivispeech,
             body.voice_voicevox, int(body.is_active), mc_id),
        )
        _audit(conn, "admin_mc_update", admin[0], body.model_dump())
        return _mc_row(conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone())


@router.post("/mcs/{mc_id}/photo")
async def upload_mc_photo(mc_id: str, admin: AdminContext, file: UploadFile = File(...)) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT photo_path FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="MC not found")
        old_filename = row["photo_path"]

    new_file = None
    try:
        photo_bytes = await _read_mc_photo(file)
        filename = f"{uuid.uuid4().hex}.webp"
        photo_dir = Path(get_settings().mc_photos_dir)
        photo_dir.mkdir(parents=True, exist_ok=True)
        new_file = photo_dir / filename
        new_file.write_bytes(photo_bytes)
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE mc_profiles SET photo_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (filename, mc_id),
            )
            _audit(conn, "admin_mc_photo_update", admin[0], {"mc_id": mc_id, "size": len(photo_bytes)})
            row = conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone()
        old_file = _stored_mc_photo_path(old_filename)
        if old_file and old_file != new_file.resolve():
            try:
                old_file.unlink(missing_ok=True)
            except OSError:
                logger.warning("Old MC photo could not be removed")
        return _mc_row(row)
    except Exception:
        if new_file is not None:
            new_file.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.delete("/mcs/{mc_id}/photo")
def delete_mc_photo(mc_id: str, admin: AdminContext) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT photo_path FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="MC not found")
        old_filename = row["photo_path"]
        conn.execute(
            "UPDATE mc_profiles SET photo_path = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (mc_id,),
        )
        _audit(conn, "admin_mc_photo_delete", admin[0], {"mc_id": mc_id})
        result = _mc_row(conn.execute("SELECT * FROM mc_profiles WHERE id = ?", (mc_id,)).fetchone())
    old_file = _stored_mc_photo_path(old_filename)
    if old_file:
        try:
            old_file.unlink(missing_ok=True)
        except OSError:
            logger.warning("MC photo could not be removed")
    return result
