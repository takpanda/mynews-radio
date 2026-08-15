"""手動で選択された辞書エントリをAIVIS Speechへ同期するAPI。"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth import require_admin
from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.aivis_user_dict_client import AivisUserDictClient
from app.services.text_normalization import has_unsupported_comma, normalize_dictionary_surface

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_admin)])


class DictionarySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dictionary_entry_ids: list[int] = Field(..., min_length=1, max_length=500)
    overwrite_confirmed: bool = False
    dry_run: bool = False

    @model_validator(mode="before")
    @classmethod
    def accept_confirmation_aliases(cls, value: Any) -> Any:
        if isinstance(value, dict) and "overwrite_confirmed" not in value:
            value = dict(value)
            for alias in ("overwrite", "confirm_overwrite"):
                if alias in value:
                    value["overwrite_confirmed"] = value.pop(alias)
                    break
        return value


def _detail(entry_id: int | None, surface: str, status: str, reason: str, **extra: Any) -> dict:
    value = {"dictionary_entry_id": entry_id, "surface": surface, "status": status, "reason": reason}
    value.update(extra)
    return value


@router.post("/admin/user_dict_sync", summary="選択した辞書エントリをAIVISへ同期")
def sync_user_dictionary(body: DictionarySyncRequest) -> dict:
    requested_ids = list(dict.fromkeys(body.dictionary_entry_ids))
    details: list[dict] = []
    rows_by_surface: dict[str, list[Any]] = defaultdict(list)

    with get_db_connection() as conn:
        placeholders = ",".join("?" for _ in requested_ids)
        rows = conn.execute(
            f"SELECT id, surface, reading, is_active, updated_at FROM dictionary_entries WHERE id IN ({placeholders})",
            requested_ids,
        ).fetchall()

    found_ids = {row["id"] for row in rows}
    for entry_id in requested_ids:
        if entry_id not in found_ids:
            details.append(_detail(entry_id, "", "skipped", "not_found"))
    for row in rows:
        if not row["is_active"]:
            details.append(_detail(row["id"], row["surface"], "skipped", "inactive"))
        else:
            rows_by_surface[row["surface"]].append(row)

    selected: list[Any] = []
    for surface, candidates in rows_by_surface.items():
        winner = max(candidates, key=lambda row: (row["updated_at"] or "", row["id"]))
        selected.append(winner)
        for row in candidates:
            if row["id"] != winner["id"]:
                details.append(_detail(row["id"], surface, "skipped", "duplicate_surface", selected_id=winner["id"]))

    # 正規化後の比較キー（NFKC + 3桁区切りカンマ除去）でAIVIS Engine側の既存項目と照合する。
    # DBの保存値（row["surface"]）は変更せず、同期結果にもそのまま表示する。
    rows_by_normalized_surface: dict[str, list[Any]] = defaultdict(list)
    for row in selected:
        normalized_surface = normalize_dictionary_surface(row["surface"])
        if has_unsupported_comma(normalized_surface):
            details.append(_detail(row["id"], row["surface"], "skipped", "unsupported_comma"))
            continue
        rows_by_normalized_surface[normalized_surface].append(row)

    to_sync: list[tuple[Any, str]] = []
    for normalized_surface, rows_for_key in rows_by_normalized_surface.items():
        if len(rows_for_key) > 1:
            conflicting_ids = [candidate["id"] for candidate in rows_for_key]
            for row in rows_for_key:
                details.append(
                    _detail(
                        row["id"],
                        row["surface"],
                        "skipped",
                        "normalized_surface_conflict",
                        conflicting_ids=[i for i in conflicting_ids if i != row["id"]],
                    )
                )
            continue
        to_sync.append((rows_for_key[0], normalized_surface))

    if not to_sync:
        return {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "added": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": len(details),
            "errors": 0,
            "details": details,
        }

    client = AivisUserDictClient(get_settings().aivispeech_base_url)
    try:
        try:
            remote_words = client.list_words()
        except Exception as exc:
            logger.error("AIVIS user dictionary unavailable: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="AIVIS Speech user dictionary is unavailable") from exc

        remote_by_normalized_surface: dict[str, list[dict]] = defaultdict(list)
        for word in remote_words:
            surface = word.get("surface")
            if surface:
                remote_by_normalized_surface[normalize_dictionary_surface(surface)].append(word)

        counts = {"added": 0, "updated": 0, "deleted": 0, "skipped": len(details), "errors": 0}
        for row, normalized_surface in to_sync:
            surface = row["surface"]
            reading = row["reading"]
            existing = remote_by_normalized_surface.get(normalized_surface, [])
            if existing and not body.overwrite_confirmed:
                counts["skipped"] += 1
                details.append(_detail(row["id"], surface, "confirmation_required", "remote_exists", remote=existing))
                continue
            if existing and all((word.get("pronunciation") or word.get("reading")) == reading for word in existing):
                counts["skipped"] += 1
                details.append(_detail(row["id"], surface, "skipped", "same_reading"))
                continue
            if body.dry_run:
                counts["skipped"] += 1
                details.append(_detail(row["id"], surface, "pending", "remote_exists" if existing else "not_found", reading=reading))
                continue
            try:
                if existing:
                    for word in existing:
                        client.update_word(str(word.get("uuid") or word.get("id")), surface, reading)
                    counts["updated"] += 1
                    details.append(_detail(row["id"], surface, "updated", "overwritten", reading=reading))
                else:
                    client.add_word(surface, reading)
                    counts["added"] += 1
                    details.append(_detail(row["id"], surface, "added", "not_found", reading=reading))
            except Exception as exc:
                counts["errors"] += 1
                details.append(_detail(row["id"], surface, "error", "aivis_api_failed"))
                logger.error("AIVIS user dictionary operation failed for entry %s: %s", row["id"], type(exc).__name__)

        return {"synced_at": datetime.now(timezone.utc).isoformat(), **counts, "details": details}
    finally:
        client.close()
