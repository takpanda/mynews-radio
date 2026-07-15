"""Misreading report submission API (BEE-432)."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])


class MisreadingReportCreate(BaseModel):
    target_text: str = Field(..., min_length=1, max_length=2000)
    correct_reading: str = Field(..., min_length=1, max_length=500)
    article_id: Optional[int] = Field(None, ge=1)
    audio_generation_id: Optional[str] = Field(None, max_length=100)
    playback_position: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)
    app_version: Optional[str] = Field(None, max_length=50)

    @field_validator("target_text", "correct_reading")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank or whitespace only")
        return v


def _format_dt(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return dt_str


def _row_to_report(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "target_text": d["target_text"],
        "correct_reading": d["correct_reading"],
        "article_id": d.get("article_id"),
        "audio_generation_id": d.get("audio_generation_id"),
        "playback_position": d.get("playback_position"),
        "notes": d.get("notes") or "",
        "app_version": d.get("app_version") or "",
        "created_at": _format_dt(d["created_at"]),
    }


def _require_article(article_id: int) -> None:
    """articles テーブルに指定IDが存在することを確認する。"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="Referenced article not found"
        )


@router.post("/reports/misreading", summary="読み間違い報告を送信", status_code=201)
def create_misreading_report(body: MisreadingReportCreate) -> dict:
    """読み間違い報告を新規登録する。

    article_id が指定された場合、articles テーブルに存在することを確認する。
    同一 target_text + correct_reading の組み合わせで直近24時間以内に
    登録済みの場合は 409 Conflict を返す（原子的な判定）。
    """
    if body.article_id is not None:
        _require_article(body.article_id)

    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO misreading_reports "
            "(target_text, correct_reading, article_id, audio_generation_id, "
            " playback_position, notes, app_version) "
            "SELECT ?, ?, ?, ?, ?, ?, ? "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM misreading_reports "
            "  WHERE target_text = ? AND correct_reading = ? "
            "  AND created_at >= datetime('now', '-24 hours')"
            ")",
            (
                body.target_text,
                body.correct_reading,
                body.article_id,
                body.audio_generation_id,
                body.playback_position,
                body.notes,
                body.app_version,
                body.target_text,
                body.correct_reading,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail="Duplicate report: same target_text and correct_reading within 24 hours",
            )
        new_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM misreading_reports WHERE id = ?", (new_id,)
        ).fetchone()

    return _row_to_report(row)
