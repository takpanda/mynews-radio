"""Health check endpoints."""

from fastapi import APIRouter

from app.services.voicevox_client import VoicevoxClient
from app.services.ollama_client import OllamaClient

router = APIRouter()


@router.get("/health/voicevox", summary="VOICEVOX Engine疎通確認")
def health_voicevox() -> dict[str, str]:
    """VOICEVOX Engineが起動しているか確認する"""
    from app.config import get_settings

    settings = get_settings()
    client = VoicevoxClient(settings.voicevox_base_url)
    try:
        result = client.health_check()
        return result
    finally:
        client.close()


@router.get("/health/ollama", summary="Ollama疎通確認")
def health_ollama() -> dict[str, str]:
    """Ollamaが起動しているか確認する"""
    from app.config import get_settings

    settings = get_settings()
    client = OllamaClient(settings.ollama_base_url, settings.ollama_model)
    try:
        result = client.health_check()
        return result
    finally:
        client.close()
