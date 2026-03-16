from datetime import datetime, date

from sqlalchemy import BIGINT, Column, Date, DateTime, Index, String

from common.db.base import Base


class DailyPick(Base):
    __tablename__ = "daily_picks"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    day_msk = Column(Date, nullable=False)  # the day the pick is announced (MSK date)
    winner_tg_id = Column(BIGINT, nullable=False)
    title = Column(String(64), nullable=False)  # e.g. "participant_of_day"
    picked_by_tg_id = Column(BIGINT, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_daily_pick_chat_day_title", "chat_id", "day_msk", "title", unique=True),
    )
