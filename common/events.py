"""Redis pub/sub для пуша баланса в Mini App (SSE).

Best-effort: если Redis недоступен / REDIS_URL не задан — тихо
ничего не делаем, основная транзакция не страдает. Публикуем
ПОСЛЕ commit. Канал на чат, в payload user_id для фильтрации.
"""
import json
import os

from common.logger.logger import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")

_client = None
_init_done = False


def _redis():
    global _client, _init_done
    if _init_done:
        return _client
    _init_done = True
    if not REDIS_URL:
        return None
    try:
        import redis

        _client = redis.from_url(
            REDIS_URL, socket_timeout=2, socket_connect_timeout=2
        )
    except Exception as exc:
        logger.warning("redis init failed: %s", str(exc)[:160])
        _client = None
    return _client


def balance_channel(chat_id: int) -> str:
    return f"bal:{chat_id}"


def publish_balance(user_id: int, chat_id: int, balance: int) -> None:
    """Опубликовать новый баланс юзера. Вызывать ПОСЛЕ commit.
    Никогда не бросает."""
    cli = _redis()
    if cli is None:
        return
    try:
        cli.publish(
            balance_channel(chat_id),
            json.dumps({"user_id": user_id, "balance": balance}),
        )
    except Exception as exc:
        logger.debug("publish_balance failed: %s", str(exc)[:120])
