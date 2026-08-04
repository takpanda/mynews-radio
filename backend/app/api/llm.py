import asyncio

from fastapi import APIRouter, Depends

from app.auth import require_owner_session
from app.services.llm_provider import discover_providers

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers", dependencies=[Depends(require_owner_session)])
async def list_llm_providers() -> dict:
    return await discover_providers()
