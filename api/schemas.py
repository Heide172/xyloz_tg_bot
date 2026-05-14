"""Pydantic схемы ответов и запросов API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    id: int
    tg_id: int
    username: Optional[str] = None
    fullname: Optional[str] = None


class BalanceResponse(BaseModel):
    chat_id: int
    balance: int
    bank: int  # общий банк чата


class MeResponse(BaseModel):
    user: UserPublic
    balance: Optional[BalanceResponse] = None


class TxItem(BaseModel):
    id: int
    amount: int
    kind: str
    note: Optional[str] = None
    created_at: datetime


class TxListResponse(BaseModel):
    items: list[TxItem]


class LeaderboardEntry(BaseModel):
    user: UserPublic
    balance: int


class LeaderboardResponse(BaseModel):
    entries: list[LeaderboardEntry]


class MarketOptionPublic(BaseModel):
    id: int
    position: int
    label: str
    pool: int
    share: float  # 0..1


class MarketPublic(BaseModel):
    id: int
    chat_id: int
    type: str
    status: str
    question: str
    options: list[MarketOptionPublic]
    total_pool: int
    bets_count: int
    closes_at: datetime
    resolved_at: Optional[datetime] = None
    winning_option_id: Optional[int] = None
    external_url: Optional[str] = None
    creator_id: Optional[int] = None
    created_at: datetime


class MarketsList(BaseModel):
    items: list[MarketPublic]


class CreateMarketRequest(BaseModel):
    question: str
    options: list[str]
    duration: str = Field(..., description="например 7d / 12h / 90m")


class CreateMarketResponse(BaseModel):
    market: MarketPublic
    fee_charged: int


class PlaceBetRequest(BaseModel):
    option_position: int
    amount: int


class PlaceBetResponse(BaseModel):
    bet_id: int
    market_id: int
    option_label: str
    option_pool_after: int
    user_balance_after: int


class PortfolioBet(BaseModel):
    bet_id: int
    market_id: int
    question: str
    status: str
    option_label: str
    amount: int
    payout: Optional[int] = None
    refunded: bool
    created_at: datetime


class PortfolioResponse(BaseModel):
    items: list[PortfolioBet]


class ImportMarketRequest(BaseModel):
    url: str


class ImportMarketResponse(BaseModel):
    market: MarketPublic
    already_imported: bool


class ErrorResponse(BaseModel):
    detail: str
