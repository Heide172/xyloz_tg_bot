from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, String, Text

from common.db.base import Base


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_by_tg_id = Column(BIGINT, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
