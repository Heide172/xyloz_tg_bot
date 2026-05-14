from fastapi import APIRouter, Depends

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from api.schemas import PortfolioBet, PortfolioResponse
from services.markets_service import user_open_positions

router = APIRouter()


@router.get("", response_model=PortfolioResponse)
async def portfolio_route(auth: TgWebAppAuth = Depends(require_auth)) -> PortfolioResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    rows = user_open_positions(chat_id=chat_id, user_id=user_id)
    items = [
        PortfolioBet(
            bet_id=r["bet_id"],
            market_id=r["market_id"],
            question=r["question"],
            status=r["status"],
            option_label=r["option_label"],
            amount=r["amount"],
            payout=r["payout"],
            refunded=r["refunded"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return PortfolioResponse(items=items)
