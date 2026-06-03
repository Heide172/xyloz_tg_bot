"""Кэш названий форум-тем: chat_id -> {topic_id: title}.

get_forum_topics дёргается один раз на чат (на kurigram), дальше из кэша —
чтобы не бить API на каждое сообщение.
"""
from common.logger import get_logger

log = get_logger("vpndigest.topics")

_cache: dict[int, dict[int, str]] = {}


async def title(app, chat_id: int, topic_id) -> str | None:
    """Название темы по её id; None если не форум / тема не найдена."""
    if topic_id is None:
        return None
    if chat_id not in _cache:
        mapping: dict[int, str] = {}
        try:
            async for t in app.get_forum_topics(chat_id):
                tid = getattr(t, "id", None)
                if tid is None:
                    tid = getattr(t, "message_thread_id", None)
                if tid is not None:
                    mapping[tid] = getattr(t, "title", None)
        except Exception as e:
            log.warning("get_forum_topics не сработал для чата %s: %s", chat_id, type(e).__name__)
        _cache[chat_id] = mapping
    return _cache.get(chat_id, {}).get(topic_id)


def invalidate(chat_id: int | None = None) -> None:
    """Сбросить кэш (напр., если в чате создали новую тему)."""
    if chat_id is None:
        _cache.clear()
    else:
        _cache.pop(chat_id, None)
