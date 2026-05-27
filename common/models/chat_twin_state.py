from datetime import datetime

from sqlalchemy import (
    BIGINT,
    Boolean,
    Column,
    DateTime,
    Date,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from common.db.base import Base


class ChatTwinState(Base):
    """Текущий «двойник дня» для чата — кого имитировать сегодня.
    Обновляется раз в сутки воркером; либо вручную через override
    (см. bot_settings: twin_override:<chat_id>:<date>).
    """
    __tablename__ = "chat_twin_state"

    chat_id = Column(BIGINT, primary_key=True)
    target_user_id = Column(BIGINT, nullable=True)
    target_tg_id = Column(BIGINT, nullable=True)
    target_name = Column(String(128), nullable=True)
    day_msk = Column(Date, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    paused_until = Column(DateTime, nullable=True)
    replies_today = Column(Integer, nullable=False, default=0)
    last_reply_at = Column(DateTime, nullable=True)
    persona_stats = Column(JSONB, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
