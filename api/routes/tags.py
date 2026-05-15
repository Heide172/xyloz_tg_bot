"""Рынок аренды кастомных Telegram-тегов."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from services.markets_service import InsufficientFunds, InvalidArgument
from services.tag_rental_service import cancel_sync, quote, rent_sync, state_sync

router = APIRouter()


class RentReq(BaseModel):
    title: str = Field(min_length=1, max_length=16)
    days: int = Field(ge=1, le=7)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.get("/state")
async def state(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(state_sync, user_id, chat_id)


@router.get("/quote")
async def quote_route(days: int, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    try:
        return {"days": days, "price": quote(days)}
    except Exception as e:
        raise _err(e)


@router.post("/rent")
async def rent(req: RentReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(
            rent_sync, user_id, auth.user.id, chat_id, req.title, req.days
        )
    except Exception as e:
        raise _err(e)


@router.post("/cancel")
async def cancel(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(cancel_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)
