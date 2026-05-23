from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="MyNews Radio API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
