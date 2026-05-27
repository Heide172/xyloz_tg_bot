from datetime import datetime

from sqlalchemy import BIGINT, Boolean, Column, DateTime, ForeignKey

from common.db.base import Base


class TwinConsent(Base):
    """Глобальный opt-out юзера от выбора его «двойником дня».
    По умолчанию участвуют все — строка появляется только при /twin_optout.
    enabled=False = опт-аут.
    """
    __tablename__ = "twin_consent"

    user_id = Column(
        BIGINT, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
