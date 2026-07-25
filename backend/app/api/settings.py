"""番組設定 CRUD API。認証未導入MVPのため単一端末・単一ユーザー。"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.generate import verify_api_key
from app.services.settings_service import (
    DURATION_PRESETS,
    THEMES,
    ProgramSettings,
    get_settings_or_default,
    reset_settings,
    save_settings,
    validate_settings,
)

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


def _response(settings: ProgramSettings) -> dict:
    return settings.to_dict()


@router.get("", response_model=SettingsPayload, dependencies=[Depends(verify_api_key)])
def get_program_settings() -> dict:
    return _response(get_settings_or_default())


@router.put("", response_model=SettingsPayload, dependencies=[Depends(verify_api_key)])
def update_program_settings(payload: SettingsPayload) -> dict:
    try:
        settings = validate_settings(**payload.model_dump())
        return _response(save_settings(settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="設定を保存できませんでした") from exc


@router.delete("", response_model=SettingsPayload, dependencies=[Depends(verify_api_key)])
def reset_program_settings() -> dict:
    try:
        return _response(reset_settings())
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="設定を初期化できませんでした") from exc
