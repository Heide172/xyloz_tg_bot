import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import (
    TgWebAppAuth,
    ensure_db_user,
    is_admin,
    is_chat_member,
    require_auth,
    require_chat_membership,
)
from api.schemas import (
    BalanceResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    MeResponse,
    TxItem,
    TxListResponse,
    UserPublic,
)
from api.serializers import user_to_schema
from services.economy_service import (
    InsufficientFunds,
    get_balance,
    get_chat_bank,
    leaderboard,
    resolve_user_by_username,
    transfer_fee,
    transfer_with_fee,
)

router = APIRouter()


class TransferReq(BaseModel):
    target: str = Field(min_length=1, description="@username или tg_id получателя")
    amount: int = Field(ge=1)
    note: str | None = None


class TransferResp(BaseModel):
    amount: int
    fee: int
    total: int
    sender_balance: int
    receiver_balance: int
    receiver_username: str | None = None


def _resolve_user(target: str):
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
    from common.db.db import SessionLocal
    from common.models.user import User

    s = SessionLocal()
    try:
        u = s.query(User).filter(User.tg_id == tg_id).first()
        if u is None:
            raise HTTPException(status_code=404, detail=f"tg_id {tg_id} не найден")
        return u
    finally:
        s.close()


@router.get("/transfer/quote")
async def transfer_quote(
    amount: int = Query(ge=1), auth: TgWebAppAuth = Depends(require_auth)
) -> dict:
    await require_chat_membership(auth)
    fee = transfer_fee(amount)
    return {"amount": amount, "fee": fee, "total": amount + fee}


@router.post("/transfer", response_model=TransferResp)
async def do_transfer(
    req: TransferReq, auth: TgWebAppAuth = Depends(require_auth)
) -> TransferResp:
    chat_id = await require_chat_membership(auth)
    sender_id = ensure_db_user(auth)
    target = _resolve_user(req.target)
    if target.id == sender_id:
        raise HTTPException(status_code=400, detail="Нельзя перевести самому себе")
    try:
        r = await asyncio.to_thread(
            transfer_with_fee, sender_id, target.id, chat_id, req.amount, req.note
        )
    except InsufficientFunds as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TransferResp(**r, receiver_username=target.username)


@router.get("/me", response_model=MeResponse)
async def me(auth: TgWebAppAuth = Depends(require_auth)) -> MeResponse:
    user_id = ensure_db_user(auth)
    from common.db.db import SessionLocal
    from common.models.user import User

    session = SessionLocal()
    try:
        u = session.query(User).filter(User.id == user_id).first()
    finally:
        session.close()
    admin_flag = is_admin(auth.user.id)
    if u is None:
        return MeResponse(user=UserPublic(id=0, tg_id=auth.user.id), is_admin=admin_flag)
    balance = None
    # Без жёсткого 403: если не участник, просто не показываем баланс.
    if auth.chat_id is not None and await is_chat_member(auth.chat_id, auth.user.id):
        bal = get_balance(user_id=u.id, chat_id=auth.chat_id, auto_start=True)
        balance = BalanceResponse(
            chat_id=auth.chat_id, balance=bal, bank=get_chat_bank(auth.chat_id)
        )
    return MeResponse(user=user_to_schema(u), balance=balance, is_admin=admin_flag)


@router.get("/balance", response_model=BalanceResponse)
async def balance(auth: TgWebAppAuth = Depends(require_auth)) -> BalanceResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    bal = get_balance(user_id=user_id, chat_id=chat_id, auto_start=True)
    return BalanceResponse(chat_id=chat_id, balance=bal, bank=get_chat_bank(chat_id))


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def leaderboard_route(
    limit: int = Query(default=20, ge=1, le=100),
    auth: TgWebAppAuth = Depends(require_auth),
) -> LeaderboardResponse:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    rows = leaderboard(chat_id=chat_id, limit=limit)
    return LeaderboardResponse(
        entries=[LeaderboardEntry(user=user_to_schema(u), balance=b) for u, b in rows],
    )


@router.get("/transactions", response_model=TxListResponse)
async def transactions(
    limit: int = Query(default=50, ge=1, le=200),
    auth: TgWebAppAuth = Depends(require_auth),
) -> TxListResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    from common.db.db import SessionLocal
    from common.models.economy_tx import EconomyTx

    session = SessionLocal()
    try:
        rows = (
            session.query(EconomyTx)
            .filter(EconomyTx.chat_id == chat_id, EconomyTx.user_id == user_id)
            .order_by(EconomyTx.created_at.desc())
            .limit(limit)
            .all()
        )
        items = [
            TxItem(id=int(r.id), amount=int(r.amount), kind=r.kind, note=r.note, created_at=r.created_at)
            for r in rows
        ]
    finally:
        session.close()
    return TxListResponse(items=items)
