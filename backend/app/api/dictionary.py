"""Dictionary entry CRUD API (admin)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.generate import verify_api_key
from app.db.connection import get_db_connection

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _require_dictionary_entry(entry_id: int) -> dict:
    """辞書エントリが存在するか確認し、なければ 404 を返す"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, surface AS word, reading, category, enabled, notes, created_at, updated_at FROM dictionary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Dictionary entry not found")
    return _row_to_entry(row)


def _row_to_entry(row) -> dict:
    entry = dict(row)
    entry["status"] = "active" if entry.pop("enabled") else "inactive"
    entry.setdefault("notes", "")
    return entry


class DictionaryCreateRequest(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)
    reading: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    notes: str = Field(default="", max_length=500)


class DictionaryUpdateRequest(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)
    reading: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    notes: str = Field(default="", max_length=500)


class DictionaryStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r"^(active|inactive)$")


@router.get("/admin/dictionary", summary="辞書エントリ一覧を取得")
def list_dictionary_entries(
    limit: Optional[int] = Query(None, ge=1, description="取得件数"),
    offset: int = Query(0, ge=0, description="取得開始位置"),
    search: Optional[str] = Query(None, description="部分一致検索（word, reading 対象）"),
    category: Optional[str] = Query(None, description="カテゴリフィルタ"),
    status: Optional[str] = Query(None, description="状態フィルタ（active / inactive）"),
):
    """辞書エントリの一覧を返す。limit 未指定時は全件、指定時はページネーション情報を含む。"""
    conditions: list[str] = []
    params: list = []

    if search:
        conditions.append("(surface LIKE ? OR reading LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if category:
        conditions.append("category = ?")
        params.append(category)

    if status == "active":
        conditions.append("enabled = 1")
    elif status == "inactive":
        conditions.append("enabled = 0")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_db_connection() as conn:
        items = conn.execute(
            f"SELECT id, surface AS word, reading, category, enabled, notes, created_at, updated_at FROM dictionary_entries WHERE {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit if limit is not None else -1, offset),
        ).fetchall()

        if limit is not None:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM dictionary_entries WHERE {where_clause}",
                params,
            ).fetchone()
            total = total_row["cnt"]

            stats_row = conn.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS active, SUM(CASE WHEN enabled = 0 THEN 1 ELSE 0 END) AS inactive FROM dictionary_entries"
            ).fetchone()

    entries = [_row_to_entry(r) for r in items]

    if limit is not None:
        return {
            "items": entries,
            "total": total,
            "has_next": (offset + limit) < total,
            "stats": {
                "total": stats_row["total"],
                "active": stats_row["active"],
                "inactive": stats_row["inactive"],
            },
        }

    return entries


@router.get("/admin/dictionary/{entry_id}", summary="辞書エントリ詳細を取得")
def get_dictionary_entry(entry_id: int) -> dict:
    """指定されたIDの辞書エントリの詳細を返す"""
    return _require_dictionary_entry(entry_id)


@router.post("/admin/dictionary", summary="辞書エントリを作成", status_code=201)
def create_dictionary_entry(body: DictionaryCreateRequest) -> dict:
    """辞書エントリを作成する"""
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO dictionary_entries(surface, reading, category, notes) VALUES (?, ?, ?, ?)",
                (body.word, body.reading, body.category, body.notes),
            )
            entry_id = cursor.lastrowid
        except Exception:
            raise HTTPException(
                status_code=409, detail="Dictionary entry already exists"
            )

        row = conn.execute(
            "SELECT id, surface AS word, reading, category, enabled, notes, created_at, updated_at FROM dictionary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()

    return _row_to_entry(row)


@router.put("/admin/dictionary/{entry_id}", summary="辞書エントリを更新")
def update_dictionary_entry(entry_id: int, body: DictionaryUpdateRequest) -> dict:
    """指定されたIDの辞書エントリを更新する"""
    _require_dictionary_entry(entry_id)

    with get_db_connection() as conn:
        try:
            conn.execute(
                "UPDATE dictionary_entries SET surface = ?, reading = ?, category = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (body.word, body.reading, body.category, body.notes, entry_id),
            )
        except Exception:
            raise HTTPException(
                status_code=409, detail="Dictionary entry already exists"
            )

        row = conn.execute(
            "SELECT id, surface AS word, reading, category, enabled, notes, created_at, updated_at FROM dictionary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()

    return _row_to_entry(row)


@router.patch("/admin/dictionary/{entry_id}/status", summary="辞書エントリの状態を切り替える")
def update_dictionary_entry_status(
    entry_id: int, body: DictionaryStatusUpdateRequest
) -> dict:
    """辞書エントリの有効/無効状態を切り替える"""
    _require_dictionary_entry(entry_id)

    enabled = 1 if body.status == "active" else 0

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE dictionary_entries SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (enabled, entry_id),
        )
        row = conn.execute(
            "SELECT id, surface AS word, reading, category, enabled, notes, created_at, updated_at FROM dictionary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()

    return _row_to_entry(row)
