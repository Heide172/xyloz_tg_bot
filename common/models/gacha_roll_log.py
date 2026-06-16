from datetime import datetime

from sqlalchemy import BIGINT, Boolean, Column, DateTime, Index, Integer, String

from common.db.base import Base


class GachaRollLog(Base):
    """Телеметрия круток для балансировки (docs/gacha_v2.md, тестовый период).

    Одна строка на выпавшего персонажа. pity_* — счётчики НА МОМЕНТ выпадения
    (до сброса). Флаги: soft/hard pity, проигран ли rate-up 50/50.
    """
    __tablename__ = "gacha_roll_log"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, nullable=False)
    chat_id = Column(BIGINT, nullable=False)
    char_id = Column(String(40), nullable=False)
    rarity = Column(String(8), nullable=False)
    pity_ssr = Column(Integer, nullable=False, default=0)
    pity_ur = Column(Integer, nullable=False, default=0)
    soft_pity = Column(Boolean, nullable=False, default=False)
    hard_pity = Column(Boolean, nullable=False, default=False)
    rate_up_win = Column(Boolean, nullable=False, default=False)  # для UR: баннерный (True) / увели (False)
    is_x10 = Column(Boolean, nullable=False, default=False)
    gem_cost = Column(Integer, nullable=False, default=0)         # цена пакета (на первой карте пакета)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_gacha_roll_log_chat_created", "chat_id", "created_at"),
        Index("idx_gacha_roll_log_char", "char_id"),
    )
