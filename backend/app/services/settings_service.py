"""MVP番組設定の契約とSQLite永続化。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.db.connection import get_db_connection

THEMES = frozenset({"technology", "business", "society", "sports", "entertainment", "general"})
DURATION_PRESETS = frozenset({"short", "normal", "long"})
DEFAULT_DURATION_PRESET = "normal"

# The selection pipeline can consume this contract without knowing the storage format.
DURATION_LIMITS: dict[str, dict[str, int]] = {
    "short": {"max_articles": 6, "min_importance_score": 4},
    "normal": {"max_articles": 10, "min_importance_score": 3},
    "long": {"max_articles": 14, "min_importance_score": 2},
}


@dataclass(frozen=True)
class ProgramSettings:
    priority_themes: tuple[str, ...] = ()
    excluded_themes: tuple[str, ...] = ()
    duration_preset: str = DEFAULT_DURATION_PRESET

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_themes": list(self.priority_themes),
            "excluded_themes": list(self.excluded_themes),
            "duration_preset": self.duration_preset,
        }

    def generation_params(self) -> dict[str, Any]:
        """生成処理へ渡す安定した契約。保存形式を公開しない。"""
        return {
            "priority_themes": list(self.priority_themes),
            "excluded_themes": list(self.excluded_themes),
            **DURATION_LIMITS[self.duration_preset],
        }


def validate_settings(
    priority_themes: list[str] | tuple[str, ...] | None = None,
    excluded_themes: list[str] | tuple[str, ...] | None = None,
    duration_preset: str = DEFAULT_DURATION_PRESET,
) -> ProgramSettings:
    priority = list(priority_themes or [])
    excluded = list(excluded_themes or [])
    if len(priority) > 3:
        raise ValueError("priority_themes must contain at most 3 items")
    for name, values in (("priority_themes", priority), ("excluded_themes", excluded)):
        if len(values) != len(set(values)):
            raise ValueError(f"{name} must not contain duplicates")
        if any(value not in THEMES for value in values):
            raise ValueError(f"{name} contains an unsupported theme")
    if duration_preset not in DURATION_PRESETS:
        raise ValueError("duration_preset must be one of: short, normal, long")
    return ProgramSettings(tuple(priority), tuple(excluded), duration_preset)


def default_settings() -> ProgramSettings:
    return ProgramSettings()


def _from_row(row: sqlite3.Row) -> ProgramSettings:
    try:
        return validate_settings(
            json.loads(row["priority_themes"]),
            json.loads(row["excluded_themes"]),
            row["duration_preset"],
        )
    except (TypeError, ValueError, json.JSONDecodeError, KeyError):
        # Corrupt legacy data must never break standard generation.
        return default_settings()


def get_settings_or_default() -> ProgramSettings:
    """設定取得に失敗しても標準生成可能な既定値を返す。"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT priority_themes, excluded_themes, duration_preset "
                "FROM user_settings WHERE id = 1"
            ).fetchone()
            return _from_row(row) if row else default_settings()
    except (sqlite3.Error, OSError):
        return default_settings()


def save_settings(settings: ProgramSettings) -> ProgramSettings:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_settings "
            "(id, priority_themes, excluded_themes, duration_preset, updated_at) "
            "VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET priority_themes=excluded.priority_themes, "
            "excluded_themes=excluded.excluded_themes, duration_preset=excluded.duration_preset, "
            "updated_at=CURRENT_TIMESTAMP",
            (json.dumps(settings.priority_themes, ensure_ascii=False),
             json.dumps(settings.excluded_themes, ensure_ascii=False), settings.duration_preset),
        )
    return settings


def reset_settings() -> ProgramSettings:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_settings WHERE id = 1")
    return default_settings()
