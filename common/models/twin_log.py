from datetime import datetime

from sqlalchemy import (
    BIGINT,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from common.db.base import Base


class TwinLog(Base):
    """Лог ответов двойника: для аудита, отладки, админской ленты."""
    __tablename__ = "twin_log"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    target_user_id = Column(
        BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    trigger_message_id = Column(BIGINT, nullable=True)
    response_text = Column(Text, nullable=False)
    cost = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="sent")  # sent|skipped|err
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_twinlog_chat_created", "chat_id", "created_at"),
    )
