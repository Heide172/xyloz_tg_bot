from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

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
    auto_level = Column(Integer, nullable=False, default=0)  # legacy автокликер (rate = auto_level * AUTO_RATE)
    # Работницы фермы: {"cherry": level, "lemon": level, ...}. Уровень 0/нет = не нанята.
    # Пассивный доход = Σ WORKER_RATE[type] * level. Тир арта по уровню.
    workers = Column(JSONB, nullable=False, default=dict)  # legacy, мигрируется в гачу
    lifetime_cp = Column(BIGINT, nullable=False, default=0)  # для будущей аналитики/инфляции

    # Гача
    pity_ssr = Column(Integer, nullable=False, default=0)   # круток без SSR+
    pity_ur = Column(Integer, nullable=False, default=0)    # круток без UR
    gacha_rolls = Column(Integer, nullable=False, default=0)
    active_heroine = Column(String(40), nullable=True)      # char_id выбранной героини
    gacha_migrated = Column(Integer, nullable=False, default=0)  # 0/1 флаг конвертации workers

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
