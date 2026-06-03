"""Нормализация Pyrogram-сообщений и live-листенер monitored-чатов."""
from datetime import datetime, timezone

from pyrogram import Client, filters
from pyrogram.types import Message as TgMessage

from common.logger import get_logger
from vpndigest import config
from vpndigest.storage import store_messages

log = get_logger("vpndigest.ingest")


def _utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def normalize(m: TgMessage) -> dict | None:
    """Pyrogram Message -> dict для vpn_messages. None = пропустить."""
    if m.service:
        return None

    text = m.text or m.caption or ""
    has_media = bool(m.media)
    if not text and not has_media:
        return None

    user = m.from_user
    username = None
    user_id = None
    if user:
        user_id = user.id
        username = user.username or " ".join(
            p for p in (user.first_name, user.last_name) if p
        ).strip() or None
    elif m.sender_chat:
        username = m.sender_chat.title

    topic_id = getattr(m, "message_thread_id", None)
    topic_title = None
    topic = getattr(m, "topic", None)
    if topic is not None:
        topic_title = getattr(topic, "title", None)

    reply_to = m.reply_to_message_id
    if reply_to is not None and topic_id is not None and reply_to == topic_id:
        reply_to = None  # это «корень» топика, а не настоящий reply

    return {
        "chat_id": m.chat.id,
        "telegram_message_id": m.id,
        "user_id": user_id,
        "username": username,
        "text": text,
        "reply_to": reply_to,
        "topic_id": topic_id,
        "topic_title": topic_title,
        "is_forwarded": bool(m.forward_date or m.forward_from or m.forward_from_chat),
        "has_media": has_media,
        "created_at": _utc_naive(m.date) or datetime.utcnow(),
        "edited_at": _utc_naive(m.edit_date),
    }


async def run_listener():
    """Long-running live-листенер: слушает monitored-чаты и пишет в vpn_messages."""
    from vpndigest.client import build_client

    app = build_client()
    chat_ids = config.MONITORED_CHAT_IDS
    if not chat_ids:
        log.warning("VPN_MONITORED_CHAT_IDS пуст — слушать нечего. Заполни .env")

    chat_filter = filters.chat(chat_ids) if chat_ids else filters.all

    @app.on_message(chat_filter)
    async def _on_message(_: Client, m: TgMessage):
        try:
            row = normalize(m)
            if row:
                store_messages([row])
        except Exception:
            log.exception("Не смог сохранить сообщение %s/%s", m.chat.id, m.id)

    log.info("vpn-userbot стартует, слушаю %d чатов", len(chat_ids))
    async with app:
        me = await app.get_me()
        log.info("Залогинен как @%s (id=%s). Жду сообщений…", me.username, me.id)
        from pyrogram import idle
        await idle()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_listener())
