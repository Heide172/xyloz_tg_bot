from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from common.db.base import Base


class AppEvent(Base):
    """Лёгкая usage-аналитика Mini App: просмотры экранов и действия."""
    __tablename__ = "app_events"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chat_id = Column(BIGINT, nullable=True)
    event = Column(String(48), nullable=False)   # view | action | ...
    props = Column(JSONB, nullable=False, default=dict)  # {route|name|...}
    ts = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_app_events_ts", "ts"),
        Index("idx_app_events_event_ts", "event", "ts"),
    )
