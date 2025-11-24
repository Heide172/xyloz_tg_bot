from common.db.base import Base
from common.db.db import engine

# Импортируем модели для регистрации в Base.metadata
from common.models.user import User
from common.models.message import Message
from common.models.reaction import Reaction

Base.metadata.create_all(bind=engine)
print("Tables created successfully")
