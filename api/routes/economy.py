from fastapi import APIRouter, Depends, Query

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
from services.economy_service import get_balance, get_chat_bank, leaderboard

router = APIRouter()


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
