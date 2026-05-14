"""Конвертация ORM-объектов в Pydantic-схемы."""
from common.models.user import User
from common.models.market import Bet, Market, MarketOption

from api.schemas import (
    MarketOptionPublic,
    MarketPublic,
    PortfolioBet,
    UserPublic,
)


def user_to_schema(user: User) -> UserPublic:
    return UserPublic(
        id=int(user.id),
        tg_id=int(user.tg_id),
        username=user.username,
        fullname=user.fullname,
    )


def market_to_schema(market: Market, options: list[MarketOption], bets_count: int) -> MarketPublic:
    total = sum(o.pool for o in options)
    return MarketPublic(
        id=int(market.id),
        chat_id=int(market.chat_id),
        type=market.type,
        status=market.status,
        question=market.question,
        options=[
            MarketOptionPublic(
                id=int(o.id),
                position=int(o.position),
                label=o.label,
                pool=int(o.pool),
                share=(o.pool / total) if total else 0.0,
            )
            for o in options
        ],
        total_pool=int(total),
        bets_count=int(bets_count),
        closes_at=market.closes_at,
        resolved_at=market.resolved_at,
        winning_option_id=int(market.winning_option_id) if market.winning_option_id else None,
        external_url=market.external_url,
        creator_id=int(market.creator_id) if market.creator_id else None,
        created_at=market.created_at,
    )


def portfolio_item(b: Bet, m: Market, o: MarketOption) -> PortfolioBet:
    return PortfolioBet(
        bet_id=int(b.id),
        market_id=int(m.id),
        question=m.question,
        status=m.status,
        option_label=o.label,
        amount=int(b.amount),
        payout=int(b.payout) if b.payout is not None else None,
        refunded=bool(b.refunded),
        created_at=b.created_at,
    )
