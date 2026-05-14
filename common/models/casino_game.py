from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from common.db.base import Base


class CasinoGame(Base):
    __tablename__ = "casino_games"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    game = Column(String(20), nullable=False)        # coinflip|dice|slots|blackjack|roulette
    bet = Column(Integer, nullable=False)
    payout = Column(Integer, nullable=False, default=0)  # gross (>=0). net = payout - bet
    status = Column(String(20), nullable=False, default="finished")  # active|finished|cancelled
    outcome = Column(String(20), nullable=True)      # win|lose|push|blackjack
    state = Column(JSONB, nullable=True)             # для многоходовых (blackjack)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_casino_games_user_chat", "user_id", "chat_id"),
        Index("idx_casino_games_status", "status"),
        Index("idx_casino_games_game", "game"),
    )
