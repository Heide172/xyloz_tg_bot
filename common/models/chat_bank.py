from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, Integer

from common.db.base import Base


class ChatBank(Base):
    __tablename__ = "chat_bank"

    chat_id = Column(BIGINT, primary_key=True)
    balance = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
