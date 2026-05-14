from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint

from common.db.base import Base


class ClickerFarm(Base):
    """Состояние фермы пер-юзер-пер-чат.

    cp_balance — текущий запас «click points». Списывается на апгрейды и
    конвертацию в гривны. last_seen_at — момент последнего апдейта; при
    следующем обращении прибавляем offline-доход (auto_level × rate × elapsed),
    но не более OFFLINE_CAP_HOURS.
    """
    __tablename__ = "clicker_farms"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BIGINT, nullable=False)

    cp_balance = Column(BIGINT, nullable=False, default=0)
    tap_level = Column(Integer, nullable=False, default=1)   # value per tap = tap_level
    auto_level = Column(Integer, nullable=False, default=0)  # rate cp/sec = auto_level * AUTO_RATE
    lifetime_cp = Column(BIGINT, nullable=False, default=0)  # для будущей аналитики/инфляции

    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # daily-cap для конвертации в гривны
    daily_converted = Column(Integer, nullable=False, default=0)  # сколько гривен за окно
    daily_window_start = Column(DateTime, nullable=False, default=datetime.utcnow)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", name="uq_clicker_farms_user_chat"),
        Index("idx_clicker_farms_chat", "chat_id"),
    )
