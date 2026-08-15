"""MVP番組設定の契約とSQLite永続化。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
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
    if set(priority) & set(excluded):
        raise ValueError("priority_themes and excluded_themes must not overlap")
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


# ---------------------------------------------------------------------------
# 音声（ボイス）設定 — AivisSpeech / VOICEVOX / Fish S2 Pro の男声・女声6項目。
# 未保存の項目は config.py の現在値をそのまま使う（DB到達不能時も同様）。
# ---------------------------------------------------------------------------

_VOICE_COLUMNS = (
    "aivispeech_speaker_male",
    "aivispeech_speaker_female",
    "voicevox_speaker_male",
    "voicevox_speaker_female",
    "fishs2pro_voice_male",
    "fishs2pro_voice_female",
)


@dataclass(frozen=True)
class VoiceSettings:
    aivispeech_speaker_male: int
    aivispeech_speaker_female: int
    voicevox_speaker_male: int
    voicevox_speaker_female: int
    fishs2pro_voice_male: str
    fishs2pro_voice_female: str

    def to_dict(self) -> dict[str, Any]:
        return {column: getattr(self, column) for column in _VOICE_COLUMNS}


def default_voice_settings() -> VoiceSettings:
    """config.py の現在値をそのまま返す（未保存時・DB到達不能時の既定値）。"""
    cfg = get_settings()
    return VoiceSettings(
        aivispeech_speaker_male=cfg.aivispeech_speaker_male,
        aivispeech_speaker_female=cfg.aivispeech_speaker_female,
        voicevox_speaker_male=cfg.voicevox_speaker_male,
        voicevox_speaker_female=cfg.voicevox_speaker_female,
        fishs2pro_voice_male=cfg.fishs2pro_voice_male,
        fishs2pro_voice_female=cfg.fishs2pro_voice_female,
    )


def validate_voice_settings(
    aivispeech_speaker_male: Any,
    aivispeech_speaker_female: Any,
    voicevox_speaker_male: Any,
    voicevox_speaker_female: Any,
    fishs2pro_voice_male: Any,
    fishs2pro_voice_female: Any,
) -> VoiceSettings:
    for name, value in (
        ("aivispeech_speaker_male", aivispeech_speaker_male),
        ("aivispeech_speaker_female", aivispeech_speaker_female),
        ("voicevox_speaker_male", voicevox_speaker_male),
        ("voicevox_speaker_female", voicevox_speaker_female),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer speaker id")
    for name, value in (
        ("fishs2pro_voice_male", fishs2pro_voice_male),
        ("fishs2pro_voice_female", fishs2pro_voice_female),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty voice name")
    return VoiceSettings(
        aivispeech_speaker_male=aivispeech_speaker_male,
        aivispeech_speaker_female=aivispeech_speaker_female,
        voicevox_speaker_male=voicevox_speaker_male,
        voicevox_speaker_female=voicevox_speaker_female,
        fishs2pro_voice_male=fishs2pro_voice_male,
        fishs2pro_voice_female=fishs2pro_voice_female,
    )


def _voice_settings_from_row(row: sqlite3.Row) -> VoiceSettings:
    defaults = default_voice_settings()
    values: dict[str, Any] = {}
    for column in _VOICE_COLUMNS:
        value = row[column]
        values[column] = value if value not in (None, "") else getattr(defaults, column)
    return VoiceSettings(**values)


def get_voice_settings_or_default() -> VoiceSettings:
    """音声設定取得に失敗しても標準生成可能な既定値を返す。

    設定行・追加カラム・DB自体のいずれが読み取れなくても、項目ごとに
    config.py の既定値へフォールバックし、生成処理を止めない。
    """
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                f"SELECT {', '.join(_VOICE_COLUMNS)} FROM user_settings WHERE id = 1"
            ).fetchone()
            return _voice_settings_from_row(row) if row else default_voice_settings()
    except (sqlite3.Error, OSError):
        return default_voice_settings()


def save_voice_settings(settings: VoiceSettings) -> VoiceSettings:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_settings "
            "(id, aivispeech_speaker_male, aivispeech_speaker_female, "
            " voicevox_speaker_male, voicevox_speaker_female, "
            " fishs2pro_voice_male, fishs2pro_voice_female, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET "
            "aivispeech_speaker_male=excluded.aivispeech_speaker_male, "
            "aivispeech_speaker_female=excluded.aivispeech_speaker_female, "
            "voicevox_speaker_male=excluded.voicevox_speaker_male, "
            "voicevox_speaker_female=excluded.voicevox_speaker_female, "
            "fishs2pro_voice_male=excluded.fishs2pro_voice_male, "
            "fishs2pro_voice_female=excluded.fishs2pro_voice_female, "
            "updated_at=CURRENT_TIMESTAMP",
            tuple(getattr(settings, column) for column in _VOICE_COLUMNS),
        )
    return settings


def resolve_tts_speakers(
    engine: str, voice_settings: VoiceSettings | None = None
) -> tuple[int, int] | tuple[str, str]:
    """生成処理向けに、指定TTSエンジンの保存済み話者値を返す。

    voice_settings 省略時は保存値（未保存項目はconfig.py既定値）を取得する。
    下位処理（synthesize_episode）へ明示的に話者値が渡された場合は、
    この関数の戻り値ではなく明示値が優先される既存契約は維持する
    （呼び出し側がこの関数の結果を明示引数として渡すのはその契約の範囲内）。
    """
    vs = voice_settings if voice_settings is not None else get_voice_settings_or_default()
    if engine == "fishs2pro":
        return vs.fishs2pro_voice_male, vs.fishs2pro_voice_female
    if engine == "voicevox":
        return vs.voicevox_speaker_male, vs.voicevox_speaker_female
    return vs.aivispeech_speaker_male, vs.aivispeech_speaker_female
