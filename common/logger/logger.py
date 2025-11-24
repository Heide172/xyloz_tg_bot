import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Создаём директорию для логов если её нет
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер для модуля.

    Args:
        name: Имя логгера (обычно __name__)

    Returns:
        logging.Logger
    """
    logger = logging.getLogger(name)

    # Если логгер уже настроен, не добавляем обработчики снова
    if logger.handlers:
        return logger

    logger.setLevel(LOG_LEVEL)

    # Форматер
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Обработчик для файла (с ротацией)
    log_file = os.path.join(LOGS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger