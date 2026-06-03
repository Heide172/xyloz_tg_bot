from datetime import datetime

from sqlalchemy import Column, BIGINT, String, Boolean, DateTime

from common.db.base import Base


class VpnMonitoredChat(Base):
    """Чат VPN-проекта под наблюдением userbot'ом. Не пересекается с основными чатами бота."""

    __tablename__ = "vpn_monitored_chats"

    id = Column(BIGINT, primary_key=True)  # telegram chat_id (-100...)
    title = Column(String(255))
    username = Column(String(255))
    is_forum = Column(Boolean, default=False)  # есть ли темы (топики)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
