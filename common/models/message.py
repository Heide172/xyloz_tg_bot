from sqlalchemy import Column, BIGINT, Integer, Float, String, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from common.db.base import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    # Основные поля
    message_id = Column(BIGINT, nullable=False)  # Для совместимости с bot
    telegram_message_id = Column(BIGINT, nullable=False)  # Для истории
    user_id = Column(BIGINT, ForeignKey("users.id"), nullable=True)
    chat_id = Column(BIGINT, nullable=False)
    text = Column(Text)

    # Поля из message_service.py
    emojis = Column(String(255))
    sticker = Column(String(255))
    media = Column(String(255))
    reply_to = Column(BIGINT)

    # Типы контента (для истории)
    message_type = Column(String(50), default='text')

    # Медиа информация (для истории)
    file_id = Column(String(255))
    file_unique_id = Column(String(255))
    file_name = Column(String(255))
    mime_type = Column(String(100))
    file_size = Column(BIGINT)

    # Дополнительная информация
    caption = Column(Text)
    has_media = Column(Boolean, default=False)
    is_forwarded = Column(Boolean, default=False)
    forward_from = Column(String(255))

    # Временные метки
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime)

    # NLP-метрики (заполняются worker'ом)
    sentiment_score = Column(Float)   # -1.0..1.0
    sentiment_label = Column(String(20))  # 'positive' | 'neutral' | 'negative'
    toxicity_score = Column(Float)    # 0.0..1.0
    topic_id = Column(Integer)
    nlp_processed_at = Column(DateTime)

    # Отношения
    user = relationship("User", back_populates="messages")
    reactions = relationship("Reaction", back_populates="message")

    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_chat_telegram_message', 'chat_id', 'telegram_message_id', unique=True),
        Index('idx_chat_message', 'chat_id', 'message_id'),
        Index('idx_user_chat', 'user_id', 'chat_id'),
        Index('idx_created_at', 'created_at'),
        Index('idx_nlp_unprocessed', 'nlp_processed_at'),
        Index('idx_chat_sentiment', 'chat_id', 'sentiment_label'),
    )