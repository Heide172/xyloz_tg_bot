from sqlalchemy import Column, BIGINT, String
from sqlalchemy.orm import relationship
from common.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BIGINT, primary_key=True)
    tg_id = Column(BIGINT, unique=True)
    username = Column(String)
    fullname = Column(String)

    messages = relationship("Message", back_populates="user")
