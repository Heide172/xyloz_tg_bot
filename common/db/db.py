from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from dotenv import load_dotenv
from common.db.base import Base

# Находим путь к .env файлу
CURRENT_FILE = Path(__file__).resolve()
COMMON_DIR = CURRENT_FILE.parent.parent  # common/
PROJECT_ROOT = COMMON_DIR.parent  # корень проекта
ENV_PATH = PROJECT_ROOT / '.env'

# Загружаем .env файл с указанием пути
load_dotenv(dotenv_path=ENV_PATH)

# Отладочная информация (можно закомментировать после исправления)
print(f"🔍 Ищем .env по пути: {ENV_PATH}")
print(f"📁 Файл существует: {ENV_PATH.exists()}")

# Создаем engine
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print(f"❌ DATABASE_URL не найден!")
    print(f"📝 Проверьте содержимое файла: {ENV_PATH}")
    print(f"💡 Убедитесь, что в .env есть строка вида:")
    print(f"   DATABASE_URL=postgresql://user:password@localhost:5432/dbname")
    raise ValueError("DATABASE_URL не найден в переменных окружения. Проверьте файл .env")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ВАЖНО: импортируем все модели ПОСЛЕ создания engine
from common.models import User, Message, Reaction

def init_db():
    """Создает все таблицы в базе данных"""
    Base.metadata.create_all(bind=engine)