"""PvP-дуэль 1v1 (только Mini App)."""
import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from services.duel_service import (
    InsufficientFunds,
    InvalidArgument,
    MarketError,
    accept_sync,
    cancel_sync,
    challenge_sync,
    decline_sync,
    list_sync,
)
from services.economy_service import resolve_user_by_username

router = APIRouter()


def _resolve_user_id(target: str) -> int:
    t = (target or "").strip()
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", t)
    if m:
        u = resolve_user_by_username(m.group(1))
        if u is None:
            raise HTTPException(status_code=404, detail=f"Юзер {target} не найден")
        return int(u.id)
    try:
        tg_id = int(t)
    except ValueError:
        raise HTTPException(status_code=400, detail="Укажи @username или tg_id")
    from common.db.db import SessionLocal
    from common.models.user import User

    s = SessionLocal()
    try:
        u = s.query(User).filter(User.tg_id == tg_id).first()
        if u is None:
            raise HTTPException(status_code=404, detail=f"tg_id {tg_id} не найден")
        return int(u.id)
    finally:
        s.close()


class ChallengeReq(BaseModel):
    opponent: str = Field(min_length=1)
    stake: int = Field(ge=1)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds, MarketError)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.get("/list")
async def duel_list(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(list_sync, user_id, chat_id)


@router.post("/challenge")
async def challenge(req: ChallengeReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    opp = _resolve_user_id(req.opponent)
    try:
        return await asyncio.to_thread(
            challenge_sync, user_id, chat_id, opp, req.stake
        )
    except Exception as e:
        raise _err(e)


@router.post("/{duel_id}/accept")
async def accept(duel_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(accept_sync, duel_id, user_id)
    except Exception as e:
        raise _err(e)


@router.post("/{duel_id}/decline")
async def decline(duel_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(decline_sync, duel_id, user_id)
    except Exception as e:
        raise _err(e)


@router.post("/{duel_id}/cancel")
async def cancel(duel_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(cancel_sync, duel_id, user_id)
    except Exception as e:
        raise _err(e)
