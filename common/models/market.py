from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from common.db.base import Base


class Market(Base):
    __tablename__ = "markets"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    type = Column(String(20), nullable=False, default="internal")  # internal | polymarket | manifold
    question = Column(Text, nullable=False)
    creator_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="open")  # open | closed | resolved | cancelled
    closes_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    winning_option_id = Column(BIGINT, nullable=True)
    external_url = Column(Text, nullable=True)
    external_id = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    options = relationship("MarketOption", back_populates="market", cascade="all, delete-orphan")
    bets = relationship("Bet", back_populates="market", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_markets_chat_status", "chat_id", "status"),
        Index("idx_markets_closes_at", "closes_at"),
    )


class MarketOption(Base):
    __tablename__ = "market_options"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    market_id = Column(BIGINT, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(200), nullable=False)
    pool = Column(Integer, nullable=False, default=0)
    position = Column(Integer, nullable=False, default=0)

    market = relationship("Market", back_populates="options")

    __table_args__ = (
        Index("idx_market_options_market", "market_id"),
    )


class Bet(Base):
    __tablename__ = "bets"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    market_id = Column(BIGINT, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(BIGINT, ForeignKey("market_options.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Integer, nullable=False)
    payout = Column(Integer, nullable=True)
    refunded = Column(Integer, nullable=False, default=0)  # 1 = возвращено при cancel
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    market = relationship("Market", back_populates="bets")

    __table_args__ = (
        Index("idx_bets_market_option", "market_id", "option_id"),
        Index("idx_bets_user", "user_id"),
    )
