"""Лента прозрачности: все значимые денежные события чата."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from common.db.db import SessionLocal
from common.models.economy_tx import EconomyTx
from common.models.user import User

router = APIRouter()

# Служебные double-entry зеркала — не показываем (есть user-side аналог).
HIDDEN_KINDS = {
    "casino_coinflip_bet_to_bank",
    "casino_dice_bet_to_bank",
    "casino_slots_bet_to_bank",
    "casino_roulette_bet_to_bank",
    "casino_blackjack_bet_to_bank",
    "casino_blackjack_double_to_bank",
    "casino_coinflip_payout_from_bank",
    "casino_dice_payout_from_bank",
    "casino_slots_payout_from_bank",
    "casino_roulette_payout_from_bank",
    "casino_blackjack_payout_from_bank",
    "market_create_fee_bank",
    "market_import_fee_bank",
    "clicker_convert_from_bank",
}


class HistoryItem(BaseModel):
    id: int
    created_at: str
    user_id: int | None
    username: str | None
    fullname: str | None
    amount: int
    kind: str
    note: str | None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    has_more: bool


@router.get("", response_model=HistoryResponse)
async def history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: TgWebAppAuth = Depends(require_auth),
) -> HistoryResponse:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)

    session = SessionLocal()
    try:
        q = (
            session.query(EconomyTx, User)
            .outerjoin(User, EconomyTx.user_id == User.id)
            .filter(
                EconomyTx.chat_id == chat_id,
                EconomyTx.user_id.isnot(None),
                ~EconomyTx.kind.in_(HIDDEN_KINDS),
            )
            .order_by(EconomyTx.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        rows = q.all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            HistoryItem(
                id=int(tx.id),
                created_at=tx.created_at.isoformat(),
                user_id=int(tx.user_id) if tx.user_id else None,
                username=u.username if u else None,
                fullname=u.fullname if u else None,
                amount=int(tx.amount),
                kind=tx.kind,
                note=tx.note,
            )
            for tx, u in rows
        ]
        return HistoryResponse(items=items, has_more=has_more)
    finally:
        session.close()
