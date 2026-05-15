from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String

from common.db.base import Base


class Duel(Base):
    """PvP 1v1: оба ставят stake, coinflip, победитель забирает 2×stake −
    комиссия (в банк чата). Эскроу: stake challenger'а списывается при
    вызове, opponent'а — при принятии."""
    __tablename__ = "duels"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    challenger_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    opponent_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    stake = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending|resolved|declined|cancelled
    winner_id = Column(BIGINT, nullable=True)
    commission = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_duels_chat_status", "chat_id", "status"),
        Index("idx_duels_opponent", "opponent_id", "status"),
        Index("idx_duels_challenger", "challenger_id", "status"),
    )
