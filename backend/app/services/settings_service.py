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

# カテゴリ別設定で選択できる女性MCは、音声サーバーの応答ではなく
# アプリケーションの許可リストで固定する。これにより、サーバー停止中も
# 管理画面の候補表示と入力検証を安定して行える。
FEMALE_MC_VOICE_ALLOWLIST = ("female", "morigawa")
CATEGORY_FEMALE_VOICE_COLUMN = "fishs2pro_category_female_voices"
FEMALE_MC_SAMPLE_TEXT = "こんにちは、ニュースの時間です。今日の主な話題をお伝えします。"
_CATEGORY_FEMALE_VOICE_CATALOG = (
    {"value": "female", "display_name": "female"},
    {"value": "morigawa", "display_name": "morigawa"},
)


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
    try:
        return validate_voice_settings(**values)
    except ValueError:
        # Corrupt legacy data must never break standard generation.
        return defaults


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


def female_mc_voice_catalog() -> list[dict[str, Any]]:
    """管理画面へ返す女性MC候補の固定カタログを返す。"""
    return [
        {
            **item,
            "sample_text": FEMALE_MC_SAMPLE_TEXT,
        }
        for item in _CATEGORY_FEMALE_VOICE_CATALOG
    ]


def validate_category_female_voices(value: Any) -> dict[str, str | None]:
    """カテゴリ別女性MC割当を検証し、未設定値を正規化する。

    保存するキーは ``EPISODE_CATEGORIES`` の固定値だけに限定する。
    部分更新は行わず、入力に含まれないカテゴリは未設定として扱う。
    """
    from app.services.episode_category_service import EPISODE_CATEGORIES

    if not isinstance(value, dict):
        raise ValueError("category_female_voices must be an object")

    valid_categories = set(EPISODE_CATEGORIES)
    unknown_categories = set(value) - valid_categories
    if unknown_categories:
        raise ValueError(f"unsupported category: {sorted(unknown_categories)[0]}")

    result: dict[str, str | None] = {}
    for category, voice in value.items():
        if voice is None or (isinstance(voice, str) and not voice.strip()):
            result[category] = None
            continue
        if not isinstance(voice, str) or voice not in FEMALE_MC_VOICE_ALLOWLIST:
            raise ValueError(f"unsupported female MC voice: {voice}")
        result[category] = voice
    return result


def get_category_female_voices_or_default() -> dict[str, str | None]:
    """保存済みカテゴリ設定を返す。DB障害・旧DBでは空の設定を返す。"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                f"SELECT {CATEGORY_FEMALE_VOICE_COLUMN} FROM user_settings WHERE id = 1"
            ).fetchone()
            if not row or not row[CATEGORY_FEMALE_VOICE_COLUMN]:
                return {}
            raw = json.loads(row[CATEGORY_FEMALE_VOICE_COLUMN])
            return validate_category_female_voices(raw)
    except (sqlite3.Error, OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        # 壊れた設定は生成を止めず、カテゴリ未設定と同じ既定値へ戻す。
        return {}


def save_category_female_voices(value: dict[str, str | None]) -> dict[str, str | None]:
    """カテゴリ別女性MC設定を検証して、既存の番組・音声設定を保持したまま保存する。"""
    normalized = validate_category_female_voices(value)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_settings (id, fishs2pro_category_female_voices, updated_at) "
            "VALUES (1, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET "
            "fishs2pro_category_female_voices=excluded.fishs2pro_category_female_voices, "
            "updated_at=CURRENT_TIMESTAMP",
            (json.dumps(normalized, ensure_ascii=False),),
        )
    return normalized


def resolve_category_female_voice(
    categories: list[str] | tuple[str, ...] | None,
    *,
    available_voices: set[str] | list[str] | tuple[str, ...] | None = None,
    fallback_voice: str | None = None,
) -> str:
    """新規Fish S2 Pro生成用にカテゴリから女性MCを解決する。

    ``available_voices`` を渡した場合は、保存済み割当が現在のFish S2 Pro
    に存在するときだけ採用する。不在・未設定時は全体の既定女性MCへ戻す。
    通信失敗時は呼び出し側が空集合を渡すことで安全にフォールバックできる。
    """
    settings = get_voice_settings_or_default()
    default_voice = fallback_voice or settings.fishs2pro_voice_female
    assignments = get_category_female_voices_or_default()
    selected: str | None = None
    for category in categories or ():
        voice = assignments.get(category)
        if voice in FEMALE_MC_VOICE_ALLOWLIST:
            selected = voice
            break

    if selected is None:
        return default_voice
    if available_voices is None or selected in set(available_voices):
        return selected
    return default_voice
