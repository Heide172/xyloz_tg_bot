from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from common.db.base import Base


class GachaCollection(Base):
    """Собранные гача-персонажи пер-юзер-пер-чат. Дубликат повышает stars
    (макс 5). copies — сколько всего выпало (для статистики/возврата сверх 5★)."""
    __tablename__ = "gacha_collection"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BIGINT, nullable=False)
    char_id = Column(String(40), nullable=False)
    stars = Column(Integer, nullable=False, default=1)
    copies = Column(Integer, nullable=False, default=1)
    obtained_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "char_id", name="uq_gacha_user_chat_char"),
        Index("idx_gacha_user_chat", "user_id", "chat_id"),
    )
