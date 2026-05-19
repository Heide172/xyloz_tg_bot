"""Приём usage-событий Mini App (best-effort, лёгкий)."""
import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth
from services.analytics_service import record_event

router = APIRouter()


class EventReq(BaseModel):
    event: str = Field(max_length=48)
    props: dict | None = None


@router.post("/event")
async def ingest(req: EventReq, auth: TgWebAppAuth = Depends(require_auth)):
    try:
        uid = await asyncio.to_thread(ensure_db_user, auth)
    except Exception:
        uid = None
    await asyncio.to_thread(
        record_event, uid, auth.chat_id, req.event, req.props
    )
    return {"ok": True}
