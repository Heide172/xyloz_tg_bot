from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, Integer, String, Text

from common.db.base import Base


class EconomyTx(Base):
    __tablename__ = "economy_tx"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chat_id = Column(BIGINT, nullable=False)
    amount = Column(Integer, nullable=False)  # положительное = пополнение, отрицательное = списание
    kind = Column(String(40), nullable=False)
    ref_id = Column(String(80), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_economy_tx_user_chat", "user_id", "chat_id"),
        Index("idx_economy_tx_chat_kind", "chat_id", "kind"),
    )
