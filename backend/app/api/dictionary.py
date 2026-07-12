"""Dictionary entry management API (BEE-417 / BEE-422)."""

import logging
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.generate import verify_api_key
from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


class DictionaryCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)
    reading: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    notes: str = Field(default="", max_length=500)


class DictionaryUpdate(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)
    reading: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    notes: str = Field(default="", max_length=500)


class DictionaryStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(active|inactive)$")


def _is_active_to_status(is_active: int) -> str:
    return "active" if is_active else "inactive"


def _row_to_dict(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "word": d["word"],
        "reading": d["reading"],
        "category": d["category"],
        "status": _is_active_to_status(d["is_active"]),
        "notes": d.get("notes", ""),
        "updated_at": _format_updated_at(d["updated_at"]),
    }


def _format_updated_at(updated_at: str) -> str:
    try:
        dt = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return updated_at


def _require_entry(entry_id: int) -> dict:
    """辞書エントリが存在することを確認し、なければ 404 を返す。"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, surface AS word, reading, category, is_active, notes, created_at, updated_at FROM dictionary_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Dictionary entry not found")
    return dict(row)


COLUMNS = "id, surface AS word, reading, category, is_active, notes, created_at, updated_at"


@router.get("/admin/dictionary", summary="辞書エントリ一覧を取得")
def list_dictionary_entries(
    limit: Optional[int] = Query(None, ge=1, description="取得件数"),
    offset: int = Query(0, ge=0, description="取得開始位置"),
    search: Optional[str] = Query(None, description="部分一致検索（word, reading 対象）"),
    category: Optional[str] = Query(None, description="カテゴリフィルタ"),
    status: Optional[str] = Query(None, pattern=r"^(active|inactive)$", description="状態フィルタ"),
) -> Union[list[dict], dict]:
    """辞書エントリの一覧を取得する。

    limit 未指定時は配列（全件）を返す。
    limit 指定時はページネーション情報を含む辞書を返す。
    """
    conditions: list[str] = []
    params: list = []

    if search:
        conditions.append("(surface LIKE ? OR reading LIKE ?)")
        like_val = f"%{search}%"
        params.extend([like_val, like_val])

    if category:
        conditions.append("category = ?")
        params.append(category)

    if status == "active":
        conditions.append("is_active = 1")
    elif status == "inactive":
        conditions.append("is_active = 0")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_db_connection() as conn:
        stats_row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive "
            "FROM dictionary_entries"
        ).fetchone()
        stats = {
            "total": stats_row["total"],
            "active": stats_row["active"],
            "inactive": stats_row["inactive"],
        }

        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM dictionary_entries WHERE {where_clause}", params
        ).fetchone()
        filtered_total = count_row["cnt"] if count_row else 0

        query = f"SELECT {COLUMNS} FROM dictionary_entries WHERE {where_clause} ORDER BY id DESC"
        query_params: list = list(params)
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            query_params.extend([limit, offset])
        elif offset > 0:
            query += " LIMIT -1 OFFSET ?"
            query_params.append(offset)

        rows = conn.execute(query, query_params).fetchall()

    items = [_row_to_dict(r) for r in rows]

    if limit is not None:
        return {
            "items": items,
            "total": filtered_total,
            "has_next": (offset + limit) < filtered_total,
            "stats": stats,
        }

    return items


@router.get("/admin/dictionary/{entry_id}", summary="辞書エントリ詳細を取得")
def get_dictionary_entry(entry_id: int) -> dict:
    """指定したIDの辞書エントリの詳細を返す。"""
    row = _require_entry(entry_id)
    return _row_to_dict(row)


@router.post("/admin/dictionary", summary="辞書エントリを作成", status_code=201)
def create_dictionary_entry(body: DictionaryCreate) -> dict:
    """辞書エントリを新規作成する。"""
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM dictionary_entries WHERE surface = ? AND reading = ?",
            (body.word, body.reading),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409, detail="Dictionary entry already exists"
            )

        cursor = conn.execute(
            "INSERT INTO dictionary_entries (surface, reading, category, notes) VALUES (?, ?, ?, ?)",
            (body.word, body.reading, body.category, body.notes),
        )
        new_id = cursor.lastrowid

        row = conn.execute(
            f"SELECT {COLUMNS} FROM dictionary_entries WHERE id = ?", (new_id,)
        ).fetchone()

    return _row_to_dict(row)


@router.put("/admin/dictionary/{entry_id}", summary="辞書エントリを更新")
def update_dictionary_entry(entry_id: int, body: DictionaryUpdate) -> dict:
    """指定したIDの辞書エントリを更新する。"""
    _require_entry(entry_id)

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM dictionary_entries WHERE surface = ? AND reading = ? AND id != ?",
            (body.word, body.reading, entry_id),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409, detail="Dictionary entry already exists"
            )

        conn.execute(
            "UPDATE dictionary_entries SET surface = ?, reading = ?, category = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.word, body.reading, body.category, body.notes, entry_id),
        )

        row = conn.execute(
            f"SELECT {COLUMNS} FROM dictionary_entries WHERE id = ?", (entry_id,)
        ).fetchone()

    return _row_to_dict(row)


@router.patch("/admin/dictionary/{entry_id}/status", summary="辞書エントリの状態を切替")
def toggle_dictionary_entry_status(entry_id: int, body: DictionaryStatusUpdate) -> dict:
    """辞書エントリの有効/無効状態を切り替える（論理削除相当）。

    active ↔ inactive の状態切替のみを行い、実際のレコードは削除しない。
    無効化されたエントリは apply_replacements() で使用されなくなる。
    """
    _require_entry(entry_id)

    is_active = 1 if body.status == "active" else 0

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE dictionary_entries SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (is_active, entry_id),
        )
        row = conn.execute(
            f"SELECT {COLUMNS} FROM dictionary_entries WHERE id = ?", (entry_id,)
        ).fetchone()

    return _row_to_dict(row)
