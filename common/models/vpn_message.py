from datetime import datetime

from sqlalchemy import Column, BIGINT, String, Text, DateTime, Boolean, Index

from common.db.base import Base


class VpnMessage(Base):
    """Сырое сообщение из VPN-чата (мониторинг userbot'ом).

    Отдельная таблица от основной `messages`, чтобы не смешивать с аналитикой бота.
    Идемпотентный upsert по (chat_id, telegram_message_id).
    """

    __tablename__ = "vpn_messages"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    chat_id = Column(BIGINT, nullable=False)
    telegram_message_id = Column(BIGINT, nullable=False)
    user_id = Column(BIGINT)
    username = Column(String(255))
    text = Column(Text)
    reply_to = Column(BIGINT)

    # Forum topics (треды)
    topic_id = Column(BIGINT)  # message_thread_id; NULL = General / не-форум
    topic_title = Column(String(255))

    is_forwarded = Column(Boolean, default=False)
    has_media = Column(Boolean, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)  # время сообщения в TG (UTC)
    edited_at = Column(DateTime)

    __table_args__ = (
        Index("uq_vpn_chat_tg_message", "chat_id", "telegram_message_id", unique=True),
        Index("idx_vpn_chat_created", "chat_id", "created_at"),
        Index("idx_vpn_chat_topic_created", "chat_id", "topic_id", "created_at"),
    )
