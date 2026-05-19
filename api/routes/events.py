"""SSE: пуш баланса в Mini App.

EventSource не умеет слать заголовки → initData и chat_id идут
query-параметрами (require_auth их поддерживает). Подписка на
Redis-канал чата, фильтр по user_id. Несколько uvicorn-воркеров —
ок: Redis фанаутит всем подписчикам.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.auth import (
    TgWebAppAuth,
    ensure_db_user,
    require_auth,
    require_chat_membership,
)
from common.events import REDIS_URL, balance_channel
from common.logger.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.get("/events")
async def events(request: Request, auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    uid = await asyncio.to_thread(ensure_db_user, auth)

    async def gen():
        # Нет Redis — только heartbeat, чтобы клиент не циклил reconnect.
        if not REDIS_URL:
            while not await request.is_disconnected():
                yield ": ping\n\n"
                await asyncio.sleep(20)
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(REDIS_URL)
        ps = r.pubsub()
        await ps.subscribe(balance_channel(chat_id))
        try:
            yield "event: ready\ndata: {}\n\n"
            last_ping = asyncio.get_event_loop().time()
            while True:
                if await request.is_disconnected():
                    break
                msg = await ps.get_message(
                    ignore_subscribe_messages=True, timeout=15.0
                )
                if msg and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                    except Exception:
                        data = None
                    if data and data.get("user_id") == uid:
                        yield f"data: {json.dumps({'balance': data['balance']})}\n\n"
                now = asyncio.get_event_loop().time()
                if now - last_ping >= 20:
                    yield ": ping\n\n"
                    last_ping = now
        finally:
            try:
                await ps.unsubscribe(balance_channel(chat_id))
                await ps.aclose()
                await r.aclose()
            except Exception:
                pass

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
