"""Социальный магазин: poke/hug, анекдот, AI-роаст."""
import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from services.markets_service import InsufficientFunds, InvalidArgument
from services.social_service import (
    JOKE_COST,
    POKE_COST,
    ROAST_COST,
    do_joke,
    do_poke,
    do_roast,
)

router = APIRouter()


def _actor_name(auth: TgWebAppAuth) -> str:
    if auth.user.username:
        return "@" + auth.user.username
    fn = (auth.user.first_name or "").strip()
    return fn or f"id{auth.user.id}"


def _resolve_target_label(target: str) -> str:
    """Берём введённую строку как @username (для упоминания в чате)."""
    t = (target or "").strip()
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", t)
    if m:
        return "@" + m.group(1)
    return t[:40] or "кто-то"


class PokeReq(BaseModel):
    target: str = Field(min_length=1)
    kind: str = "poke"  # poke | hug | highfive


class JokeReq(BaseModel):
    topic: str = Field(min_length=2, max_length=120)


class RoastReq(BaseModel):
    target: str = Field(min_length=1)


class ActionResp(BaseModel):
    text: str
    cost: int
    user_balance: int


class PricesResp(BaseModel):
    poke: int
    joke: int
    roast: int


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.get("/prices", response_model=PricesResp)
async def prices(auth: TgWebAppAuth = Depends(require_auth)) -> PricesResp:
    await require_chat_membership(auth)
    return PricesResp(poke=POKE_COST, joke=JOKE_COST, roast=ROAST_COST)


@router.post("/poke", response_model=ActionResp)
async def poke(req: PokeReq, auth: TgWebAppAuth = Depends(require_auth)) -> ActionResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(
            do_poke, user_id, chat_id, _actor_name(auth),
            _resolve_target_label(req.target), req.kind,
        )
        return ActionResp(**r)
    except Exception as e:
        raise _err(e)


@router.post("/joke", response_model=ActionResp)
async def joke(req: JokeReq, auth: TgWebAppAuth = Depends(require_auth)) -> ActionResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(
            do_joke, user_id, chat_id, _actor_name(auth), req.topic
        )
        return ActionResp(**r)
    except Exception as e:
        raise _err(e)


@router.post("/roast", response_model=ActionResp)
async def roast(req: RoastReq, auth: TgWebAppAuth = Depends(require_auth)) -> ActionResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(
            do_roast, user_id, chat_id, _actor_name(auth),
            _resolve_target_label(req.target),
        )
        return ActionResp(**r)
    except Exception as e:
        raise _err(e)
