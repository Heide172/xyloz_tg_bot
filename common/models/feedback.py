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


class Feedback(Base):
    """Обратная связь из Mini App: баг-репорт или пожелание."""
    __tablename__ = "feedback"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chat_id = Column(BIGINT, nullable=True)
    kind = Column(String(16), nullable=False)  # bug | idea
    text = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="new")  # new | seen | done
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reward = Column(Integer, nullable=False, default=0)
    rewarded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_feedback_kind_status", "kind", "status"),
        Index("idx_feedback_created", "created_at"),
    )
