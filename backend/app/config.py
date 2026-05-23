from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    api_port: int = 8000
    web_port: int = 3000
    database_url: str = "sqlite:////app/data/mynews-radio.db"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    dgx_host: str = "192.168.1.103"
    ollama_base_url: str = "http://192.168.1.103:11434"
    ollama_model: str = "qwen3.6:35b"
    voicevox_base_url: str = "http://192.168.1.102:50021"
    voicevox_speaker_male: int = 11
    voicevox_speaker_female: int = 2

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
