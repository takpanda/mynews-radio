"""番組設定 CRUD API。認証未導入MVPのため単一端末・単一ユーザー。"""

import logging
import sqlite3
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth import require_owner_session
from app.config import get_settings
from app.services.fishs2pro_client import FishS2ProClient
from app.services.settings_service import (
    DURATION_PRESETS,
    FEMALE_MC_VOICE_ALLOWLIST,
    female_mc_voice_catalog,
    get_category_female_voices_or_default,
    THEMES,
    ProgramSettings,
    VoiceSettings,
    get_settings_or_default,
    get_voice_settings_or_default,
    reset_settings,
    save_settings,
    save_voice_settings,
    save_category_female_voices,
    validate_settings,
    validate_voice_settings,
)
from app.services.episode_category_service import EPISODE_CATEGORIES
from app.services.voicevox_client import VoicevoxClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority_themes: list[str] = Field(default_factory=list, max_length=3)
    excluded_themes: list[str] = Field(default_factory=list)
    duration_preset: str = "normal"

    @field_validator("priority_themes", "excluded_themes")
    @classmethod
    def validate_themes(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("themes must not contain duplicates")
        invalid = sorted(set(values) - THEMES)
        if invalid:
            raise ValueError(f"unsupported theme: {invalid[0]}")
        return values

    @field_validator("duration_preset")
    @classmethod
    def validate_duration(cls, value: str) -> str:
        if value not in DURATION_PRESETS:
            raise ValueError("duration_preset must be one of: short, normal, long")
        return value

    @model_validator(mode="after")
    def validate_theme_overlap(self) -> "SettingsPayload":
        if set(self.priority_themes) & set(self.excluded_themes):
            raise ValueError("priority_themes and excluded_themes must not overlap")
        return self


def _response(settings: ProgramSettings) -> dict:
    return settings.to_dict()


@router.get("", response_model=SettingsPayload, dependencies=[Depends(require_owner_session)])
def get_program_settings() -> dict:
    return _response(get_settings_or_default())


@router.put("", response_model=SettingsPayload, dependencies=[Depends(require_owner_session)])
def update_program_settings(payload: SettingsPayload) -> dict:
    try:
        settings = validate_settings(**payload.model_dump())
        return _response(save_settings(settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="設定を保存できませんでした") from exc


@router.delete("", response_model=SettingsPayload, dependencies=[Depends(require_owner_session)])
def reset_program_settings() -> dict:
    try:
        return _response(reset_settings())
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="設定を初期化できませんでした") from exc


# ---------------------------------------------------------------------------
# 音声（ボイス）設定 — AivisSpeech / VOICEVOX / Fish S2 Pro の男声・女声。
# ---------------------------------------------------------------------------

class VoiceSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aivispeech_speaker_male: int
    aivispeech_speaker_female: int
    voicevox_speaker_male: int
    voicevox_speaker_female: int
    fishs2pro_voice_male: str
    fishs2pro_voice_female: str

    @field_validator(
        "aivispeech_speaker_male", "aivispeech_speaker_female",
        "voicevox_speaker_male", "voicevox_speaker_female",
        mode="before",
    )
    @classmethod
    def require_json_integer_speaker_id(cls, value: object) -> object:
        # Pydantic の通常の int は文字列数値・float を変換して受理するため、
        # API 契約どおり JSON の整数値だけを許可する。
        if type(value) is not int:
            raise ValueError("must be an integer speaker id")
        return value

    @field_validator("fishs2pro_voice_male", "fishs2pro_voice_female")
    @classmethod
    def reject_blank_voice_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty voice name")
        return value


def _voice_response(settings: VoiceSettings) -> dict:
    return settings.to_dict()


@router.get("/voices", response_model=VoiceSettingsPayload, dependencies=[Depends(require_owner_session)])
def get_voice_settings() -> dict:
    """未保存の項目は config.py の現在値を返す。"""
    return _voice_response(get_voice_settings_or_default())


@router.put("/voices", response_model=VoiceSettingsPayload, dependencies=[Depends(require_owner_session)])
def update_voice_settings(payload: VoiceSettingsPayload) -> dict:
    try:
        settings = validate_voice_settings(**payload.model_dump())
        return _voice_response(save_voice_settings(settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="音声設定を保存できませんでした") from exc


class VoiceOption(BaseModel):
    display_name: str
    value: int | str
    speaker_name: str | None = None
    style_name: str | None = None


class EngineVoiceOptions(BaseModel):
    status: str
    options: list[VoiceOption] = Field(default_factory=list)
    error: str | None = None


class VoiceOptionsResponse(BaseModel):
    aivispeech: EngineVoiceOptions
    voicevox: EngineVoiceOptions
    fishs2pro: EngineVoiceOptions


class FemaleMcSample(BaseModel):
    url: str
    text: str
    media_type: str
    available: bool


class FemaleMcOption(BaseModel):
    display_name: str
    value: str
    sample: FemaleMcSample


class CategoryFemaleMcResponse(BaseModel):
    categories: list[str]
    category_female_voices: dict[str, str | None]
    default_voice: str
    voices: list[FemaleMcOption]


class CategoryFemaleMcPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_female_voices: dict[str, str | None] | None = None
    settings: dict[str, str | None] | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_mapping_payload(cls, value: object) -> object:
        # Frontend契約は category_female_voices だが、単純なカテゴリ→ボイス
        # オブジェクトも受け入れてAPI利用者の移行を容易にする。
        if isinstance(value, dict) and not ({"category_female_voices", "settings"} & value.keys()):
            return {"category_female_voices": value}
        return value

    @model_validator(mode="after")
    def merge_settings_alias(self) -> "CategoryFemaleMcPayload":
        if self.category_female_voices is not None and self.settings is not None:
            if self.category_female_voices != self.settings:
                raise ValueError("category_female_voices and settings must match")
        if self.category_female_voices is None:
            self.category_female_voices = self.settings or {}
        return self


# 一覧取得失敗時にクライアント例外の詳細（接続先ホスト等）を応答へそのまま含めない。
_VOICE_LIST_FAILURE_MESSAGE = "話者一覧を取得できませんでした"


def _fetch_speaker_style_options(base_url: str) -> EngineVoiceOptions:
    client = VoicevoxClient(base_url)
    try:
        speakers = client.list_speakers()
        options = [
            VoiceOption(
                display_name=f"{item['speaker_name']} - {item['style_name']}",
                value=item["value"],
                speaker_name=item["speaker_name"],
                style_name=item["style_name"],
            )
            for item in speakers
        ]
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("話者一覧の取得に失敗しました: %s", type(exc).__name__)
        return EngineVoiceOptions(status="error", options=[], error=_VOICE_LIST_FAILURE_MESSAGE)
    finally:
        client.close()
    return EngineVoiceOptions(status="ok", options=options)


def _fetch_fishs2pro_options(base_url: str) -> EngineVoiceOptions:
    client = FishS2ProClient(base_url)
    try:
        voices = client.list_voices()
        options = [VoiceOption(display_name=voice, value=voice) for voice in voices]
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Fish S2 Pro のボイス一覧取得に失敗しました: %s", type(exc).__name__)
        return EngineVoiceOptions(status="error", options=[], error=_VOICE_LIST_FAILURE_MESSAGE)
    finally:
        client.close()
    return EngineVoiceOptions(status="ok", options=options)


@router.get(
    "/voices/options",
    response_model=VoiceOptionsResponse,
    dependencies=[Depends(require_owner_session)],
)
def get_voice_options() -> dict:
    """3エンジン分の話者・スタイル（またはボイス名）候補を共通形式で返す。

    1エンジンの取得に失敗しても他エンジンの結果は返す（status="error" で識別）。
    """
    cfg = get_settings()
    return {
        "aivispeech": _fetch_speaker_style_options(cfg.aivispeech_base_url).model_dump(),
        "voicevox": _fetch_speaker_style_options(cfg.voicevox_base_url).model_dump(),
        "fishs2pro": _fetch_fishs2pro_options(cfg.fishs2pro_base_url).model_dump(),
    }


def _female_mc_sample_path(voice_name: str) -> Path:
    cfg = get_settings()
    sample_dir = getattr(cfg, "fishs2pro_voice_sample_dir", "/app/data/voice-samples")
    # voice_name は許可リスト照合済みで、ファイル名を外部入力から組み立てない。
    return Path(sample_dir) / f"{voice_name}.wav"


def _category_female_mc_response() -> dict:
    assignments = get_category_female_voices_or_default()
    defaults = get_voice_settings_or_default()
    default_voice = defaults.fishs2pro_voice_female
    voices = []
    for voice in female_mc_voice_catalog():
        voice_name = voice["value"]
        voices.append({
            "display_name": voice["display_name"],
            "value": voice_name,
            "sample": {
                "url": f"/settings/voices/categories/samples/{voice_name}",
                "text": voice["sample_text"],
                "media_type": "audio/wav",
                "available": _female_mc_sample_path(voice_name).is_file(),
            },
        })
    return {
        "categories": list(EPISODE_CATEGORIES),
        "category_female_voices": {
            category: assignments.get(category)
            for category in EPISODE_CATEGORIES
        },
        "default_voice": default_voice,
        "voices": voices,
    }


@router.get(
    "/voices/categories",
    response_model=CategoryFemaleMcResponse,
    dependencies=[Depends(require_owner_session)],
)
def get_category_female_mc_settings() -> dict:
    """15固定カテゴリの女性MC設定と固定試聴サンプル情報を返す。"""
    return _category_female_mc_response()


@router.put(
    "/voices/categories",
    response_model=CategoryFemaleMcResponse,
    dependencies=[Depends(require_owner_session)],
)
def update_category_female_mc_settings(payload: CategoryFemaleMcPayload) -> dict:
    """カテゴリ別女性MC設定を検証・保存する（既存管理者セッション必須）。"""
    try:
        save_category_female_voices(payload.category_female_voices or {})
        return _category_female_mc_response()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="カテゴリ別音声設定を保存できませんでした") from exc


@router.get(
    "/voices/categories/samples/{voice_name}",
    dependencies=[Depends(require_owner_session)],
)
def get_category_female_mc_sample(voice_name: str) -> FileResponse:
    """許可済み女性MCの事前生成済み固定サンプルだけを認証付きで配信する。"""
    if voice_name not in FEMALE_MC_VOICE_ALLOWLIST:
        raise HTTPException(status_code=404, detail="Voice sample not found")
    sample_path = _female_mc_sample_path(voice_name)
    if not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Voice sample not found")
    return FileResponse(
        sample_path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=3600"},
    )
