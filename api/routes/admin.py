"""Admin API: операции, которые раньше были в /admin_adjust, /market_*, и т.д."""
import asyncio
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, is_admin, require_auth, require_chat_membership
from common.db.db import SessionLocal
from common.models.chat_bank import ChatBank
from common.models.economy_tx import EconomyTx
from common.models.user_balance import UserBalance
from services.economy_service import (
    InsufficientFunds,
    credit,
    debit,
    resolve_user_by_username,
)
from services.markets_service import (
    InvalidArgument,
    MarketError,
    MarketNotFound,
    cancel_market,
    resolve_market,
)

router = APIRouter()


def _ensure_admin(auth: TgWebAppAuth) -> None:
    if not is_admin(auth.user.id):
        raise HTTPException(status_code=403, detail="Только для админов бота.")


# ---------------- balance / bank adjust ----------------


class BalanceAdjustReq(BaseModel):
    target: str = Field(min_length=1, description="@username или tg_id")
    amount: int = Field(description="±N — может быть отрицательным")
    note: Optional[str] = None


class BalanceAdjustResp(BaseModel):
    user_id: int
    username: Optional[str] = None
    new_balance: int


def _resolve_target_user(target: str):
    target = target.strip()
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", target)
    if m:
        u = resolve_user_by_username(m.group(1))
        if u is None:
            raise HTTPException(status_code=404, detail=f"Юзер {target} не найден")
        return u
    try:
        tg_id = int(target)
    except ValueError:
        raise HTTPException(status_code=400, detail="Укажи @username или tg_id")
    from common.models.user import User

    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == tg_id).first()
        if u is None:
            raise HTTPException(status_code=404, detail=f"tg_id {tg_id} не найден")
        return u
    finally:
        session.close()


def _do_balance_adjust(chat_id: int, target_user_id: int, amount: int, note: Optional[str]) -> int:
    if amount == 0:
        raise InvalidArgument("Сумма не должна быть нулевой")
    if amount > 0:
        return credit(target_user_id, chat_id, amount, kind="admin_adjust", note=note)
    return debit(target_user_id, chat_id, -amount, kind="admin_adjust", note=note)


@router.post("/balance_adjust", response_model=BalanceAdjustResp)
async def balance_adjust(req: BalanceAdjustReq, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    target = _resolve_target_user(req.target)
    try:
        new_balance = await asyncio.to_thread(
            _do_balance_adjust, chat_id, target.id, req.amount, req.note
        )
    except InsufficientFunds as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BalanceAdjustResp(user_id=target.id, username=target.username, new_balance=new_balance)


class BankAdjustReq(BaseModel):
    amount: int
    note: Optional[str] = None


class BankAdjustResp(BaseModel):
    new_balance: int


def _do_bank_adjust(chat_id: int, amount: int, note: Optional[str]) -> int:
    session = SessionLocal()
    try:
        bank = session.query(ChatBank).filter(ChatBank.chat_id == chat_id).with_for_update().first()
        if bank is None:
            bank = ChatBank(chat_id=chat_id, balance=0)
            session.add(bank)
            session.flush()
        new_balance = bank.balance + amount
        if new_balance < 0:
            raise InvalidArgument(f"Банк не уйдёт в минус: текущий {bank.balance}, минимум {-bank.balance}")
        bank.balance = new_balance
        bank.updated_at = datetime.utcnow()
        session.add(EconomyTx(
            user_id=None,
            chat_id=chat_id,
            amount=amount,
            kind="admin_bank_adjust",
            note=note,
        ))
        session.commit()
        return new_balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/bank_adjust", response_model=BankAdjustResp)
async def bank_adjust(req: BankAdjustReq, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    if req.amount == 0:
        raise HTTPException(status_code=400, detail="Сумма не должна быть нулевой")
    try:
        nb = await asyncio.to_thread(_do_bank_adjust, chat_id, req.amount, req.note)
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BankAdjustResp(new_balance=nb)


# ---------------- markets resolve / cancel ----------------
# (создание и импорт рынков — публичные, см. api/routes/markets.py)


class MarketResolveReq(BaseModel):
    winning_option_position: int = Field(ge=1)


@router.post("/markets/{market_id}/resolve")
async def markets_resolve(
    market_id: int, req: MarketResolveReq, auth: TgWebAppAuth = Depends(require_auth)
):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    # Проверка что рынок этого чата делается внутри resolve_market.
    try:
        result = await asyncio.to_thread(
            resolve_market, market_id=market_id, winning_option_position=req.winning_option_position
        )
    except MarketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/markets/{market_id}/cancel")
async def markets_cancel(market_id: int, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    await require_chat_membership(auth)
    try:
        result = await asyncio.to_thread(cancel_market, market_id)
    except MarketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result
