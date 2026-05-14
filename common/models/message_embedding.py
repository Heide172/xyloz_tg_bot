from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BIGINT, Column, DateTime, ForeignKey

from common.db.base import Base


class MessageEmbedding(Base):
    __tablename__ = "message_embeddings"

    message_id = Column(BIGINT, ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    chat_id = Column(BIGINT, nullable=False, index=True)
    embedding = Column(Vector(768), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
