from fastapi import FastAPI

from app.config import get_settings
from app.services.voicevox_client import VoicevoxClient

settings = get_settings()
app = FastAPI(title="MyNews Radio API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/voicevox")
def health_voicevox() -> dict[str, str]:
    """VOICEVOX Engine health check endpoint.
    
    Returns status=ok when engine is up, status=error otherwise.
    """
    client = VoicevoxClient(settings.voicevox_base_url)
    result = client.health_check()
    client.close()
    return result
