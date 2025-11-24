from sqlalchemy import Column, BIGINT, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from common.db.base import Base

class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(BIGINT, primary_key=True)
    message_id = Column(BIGINT, ForeignKey("messages.id"))
    user_id = Column(BIGINT, ForeignKey("users.id"))
    emoji = Column(String)
    date = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    message = relationship("Message", back_populates="reactions")
