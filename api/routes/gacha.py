"""Гача-ферма API: крутка, коллекция, выбор героини, баннер (admin)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import (
    TgWebAppAuth,
    ensure_db_user,
    is_admin,
    require_auth,
    require_chat_membership,
)
from services.gacha_service import (
    InsufficientFunds,
    InvalidArgument,
    collection_sync,
    roll_sync,
    set_banner,
    set_heroine_sync,
)

router = APIRouter()


class RollReq(BaseModel):
    count: int = Field(default=1)


class HeroineReq(BaseModel):
    char_id: str


class BannerReq(BaseModel):
    char_id: str


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.get("/collection")
async def collection(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(collection_sync, user_id, chat_id)


@router.post("/roll")
async def roll(req: RollReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(roll_sync, user_id, chat_id, req.count)
    except Exception as e:
        raise _err(e)


@router.post("/heroine")
async def heroine(req: HeroineReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(set_heroine_sync, user_id, chat_id, req.char_id)
    except Exception as e:
        raise _err(e)


@router.post("/banner")
async def banner(req: BannerReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    if not is_admin(auth.user.id):
        raise HTTPException(status_code=403, detail="Только для админов бота")
    try:
        await asyncio.to_thread(set_banner, req.char_id)
        return {"banner": req.char_id}
    except Exception as e:
        raise _err(e)
