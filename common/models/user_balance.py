from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint

from common.db.base import Base


class UserBalance(Base):
    __tablename__ = "user_balance"

    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BIGINT, nullable=False)
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "chat_id"),
        Index("idx_user_balance_chat", "chat_id"),
    )
