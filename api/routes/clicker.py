"""Кликер-ферма API."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from services.clicker_service import (
    ClickerError,
    InsufficientFunds,
    InvalidArgument,
    MarketError,
    buy_cp_sync,
    convert_sync,
    get_state_sync,
    hire_worker_sync,
    tap_sync,
    upgrade_auto_sync,
    upgrade_tap_sync,
)
from services.market_service import price_history, quote_sync

router = APIRouter()


class FarmStateResp(BaseModel):
    cp_balance: int
    tap_level: int
    auto_level: int
    auto_rate_cps: float
    next_tap_cost: int
    next_auto_cost: int
    bank_balance: int
    user_balance: int
    lifetime_cp: int
    cp_per_hryvnia: float
    offline_cap_seconds: int
    workers: list = []


class TapReq(BaseModel):
    # elapsed без жёсткого потолка: при сворачивании Telegram-вебвью
    # таймеры замораживаются и при возврате elapsed огромный — это норма,
    # сервер всё равно кэпит accepted по MAX_CPS.
    count: int = Field(ge=1, le=5000)
    elapsed_ms: int = Field(ge=1)


class ConvertReq(BaseModel):
    cp_amount: int = Field(ge=1)


class BuyReq(BaseModel):
    hryvnia_amount: int = Field(ge=1)


def _map_err(e: Exception) -> HTTPException:
    if isinstance(e, InvalidArgument):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, InsufficientFunds):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, (ClickerError, MarketError)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=FarmStateResp)
async def get_state(auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(get_state_sync, user_id, chat_id)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/tap", response_model=FarmStateResp)
async def tap(req: TapReq, auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(tap_sync, user_id, chat_id, req.count, req.elapsed_ms)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/upgrade/tap", response_model=FarmStateResp)
async def upgrade_tap(auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(upgrade_tap_sync, user_id, chat_id)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/upgrade/auto", response_model=FarmStateResp)
async def upgrade_auto(auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(upgrade_auto_sync, user_id, chat_id)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/hire/{wtype}", response_model=FarmStateResp)
async def hire_worker(wtype: str, auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(hire_worker_sync, user_id, chat_id, wtype)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/convert", response_model=FarmStateResp)
async def convert(req: ConvertReq, auth: TgWebAppAuth = Depends(require_auth)):
    """Продать cp на AMM-рынок → гривны (со slippage)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(convert_sync, user_id, chat_id, req.cp_amount)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.post("/buy", response_model=FarmStateResp)
async def buy(req: BuyReq, auth: TgWebAppAuth = Depends(require_auth)):
    """Обратный поток: купить cp за гривны через AMM (давит курс вверх)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        s = await asyncio.to_thread(buy_cp_sync, user_id, chat_id, req.hryvnia_amount)
        return FarmStateResp(**s.asdict())
    except Exception as e:
        raise _map_err(e)


@router.get("/market")
async def market_quote(auth: TgWebAppAuth = Depends(require_auth)):
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    try:
        q = await asyncio.to_thread(quote_sync, chat_id)
        hist = await asyncio.to_thread(price_history, chat_id, 200)
        return {**q, "history": hist}
    except Exception as e:
        raise _map_err(e)
