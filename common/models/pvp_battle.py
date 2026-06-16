from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from common.db.base import Base


class PvpBattle(Base):
    """Лог боя гача-v2 (для телеметрии теста и переигровки анимации).

    kind: matchmake | duel. team_a/team_b — снимок составов на момент боя
    (char_id/stars/level/stats), log — массив событий раундов.
    """
    __tablename__ = "pvp_battles"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    kind = Column(String(16), nullable=False, default="matchmake")
    a_user_id = Column(BIGINT, nullable=True)
    b_user_id = Column(BIGINT, nullable=True)   # null = бот-команда
    winner = Column(String(4), nullable=False)  # a | b | draw
    winner_user_id = Column(BIGINT, nullable=True)
    rounds = Column(Integer, nullable=False, default=0)
    stake = Column(Integer, nullable=False, default=0)
    team_a = Column(JSONB, nullable=False, default=list)
    team_b = Column(JSONB, nullable=False, default=list)
    log = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_pvp_battles_chat_created", "chat_id", "created_at"),
        Index("idx_pvp_battles_a", "a_user_id"),
    )
