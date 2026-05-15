from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String

from common.db.base import Base


class TagRental(Base):
    """Аренда кастомного Telegram-тега. Один активный title на чат
    (уникальность по тексту), один активный rental на юзера. По истечении
    scheduler снимает Telegram custom_title."""
    __tablename__ = "tag_rentals"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    tg_user_id = Column(BIGINT, nullable=False)  # для Bot API
    title = Column(String(32), nullable=False)
    price_paid = Column(Integer, nullable=False, default=0)
    rented_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="active")  # active|expired|cancelled
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_tagr_chat_status", "chat_id", "status"),
        Index("idx_tagr_user_status", "user_id", "status"),
        Index("idx_tagr_expires", "status", "expires_at"),
    )
