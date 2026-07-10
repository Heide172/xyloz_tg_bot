from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User
from common.models.reaction import Reaction
from common.logger.logger import get_logger
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
import emoji


def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return value

logger = get_logger(__name__)

def save_message(tg_message):
    session = SessionLocal()

    try:
        # --- сохраняем пользователя
        user = session.query(User).filter_by(tg_id=tg_message.from_user.id).first()
        if not user:
            user = User(
                tg_id=tg_message.from_user.id,
                username=tg_message.from_user.username,
                fullname=tg_message.from_user.full_name
            )
            session.add(user)
            session.flush()

        # --- сохраняем сообщение
        msg = Message(
            message_id=tg_message.message_id,
            telegram_message_id=tg_message.message_id,  # Дублируем для совместимости
            chat_id=tg_message.chat.id,
            user_id=user.id,
            text=tg_message.text,
            # для стикер-сообщений храним эмодзи стикера — по нему подбираем
            # релевантный стикер в «муте бота» (relevant_sticker).
            emojis=(
                "".join(e for e in tg_message.text if emoji.is_emoji(e))
                if tg_message.text
                else (tg_message.sticker.emoji if tg_message.sticker else None)
            ),
            sticker=tg_message.sticker.file_id if tg_message.sticker else None,
            media=tg_message.photo[-1].file_id if tg_message.photo else None,
            reply_to=tg_message.reply_to_message.message_id if tg_message.reply_to_message else None,
            created_at=_to_datetime(tg_message.date) or datetime.utcnow(),
            edited_at=_to_datetime(tg_message.edit_date),
        )

        session.add(msg)
        session.commit()
        logger.info(f"Saved message {tg_message.message_id} from user {user.tg_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"DB ERROR: {e}", exc_info=True)
    finally:
        session.close()


def save_reaction(event):
    """MessageReactionUpdated → строка reactions.

    event.message_id — telegram id, а Reaction.message_id ссылается на
    внутренний Message.id, поэтому резолвим по (chat_id, telegram_message_id).
    Аноним/реакция от имени чата/снятие/кастом-эмодзи — пропускаем."""
    user = getattr(event, "user", None)
    if user is None:
        return  # анонимная реакция или от имени чата — не атрибутируем

    emoji_str = None
    for r in (event.new_reaction or []):
        e = getattr(r, "emoji", None)  # ReactionTypeEmoji
        if e:
            emoji_str = e
            break
    if not emoji_str:
        return  # реакцию сняли или это кастом-эмодзи — не логируем

    session = SessionLocal()
    try:
        msg = (
            session.query(Message)
            .filter(
                Message.chat_id == event.chat.id,
                Message.telegram_message_id == event.message_id,
            )
            .first()
        )
        if msg is None:
            return  # сообщение не в нашей истории — привязать не к чему

        u = session.query(User).filter_by(tg_id=user.id).first()
        if not u:
            u = User(tg_id=user.id, username=user.username, fullname=user.full_name)
            session.add(u)
            session.flush()

        session.add(Reaction(message_id=msg.id, user_id=u.id, emoji=emoji_str))
        session.commit()
        logger.info(
            "Saved reaction %s on msg %s from %s", emoji_str, event.message_id, user.id
        )
    except Exception as e:
        session.rollback()
        logger.error(f"DB ERROR: {e}", exc_info=True)
    finally:
        session.close()


# sentiment_label (NLP от воркера) → корзина эмодзи для подбора стикера по тону.
_SENTIMENT_EMOJI = {
    "positive": ["😂", "😁", "😊", "🔥", "👍", "❤️", "😎", "🥰", "💪", "🎉"],
    "negative": ["😢", "😭", "😡", "💀", "🤬", "😔", "😩", "🙄", "😤", "🤡"],
    "neutral": ["🤔", "😐", "🤷", "👀", "🫠", "😶"],
}


def _emojis_in(text: str | None) -> list[str]:
    if not text:
        return []
    return list({c for c in text if emoji.is_emoji(c)})


def _recent_chat_sentiment(session, chat_id: int, cutoff) -> str | None:
    """Доминирующий sentiment_label чата за окно (из посчитанного воркером)."""
    row = (
        session.query(Message.sentiment_label, func.count(Message.id))
        .filter(
            Message.chat_id == chat_id,
            Message.sentiment_label.isnot(None),
            Message.created_at >= cutoff,
        )
        .group_by(Message.sentiment_label)
        .order_by(func.count(Message.id).desc())
        .first()
    )
    return row[0] if row else None


def relevant_sticker(chat_id: int, text: str | None = None, days: int = 7) -> str | None:
    """Стикер file_id из отправленных в чате за `days` дней, подобранный к
    сообщению: сперва по эмодзи в тексте, затем по тону чата (sentiment),
    иначе рандом. None — если стикеров в чате нет. Для «мута бота» (/duelbot)."""
    session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        base = session.query(Message.sticker).filter(
            Message.chat_id == chat_id,
            Message.sticker.isnot(None),
            Message.created_at >= cutoff,
        )
        # 1. эмодзи из самого сообщения
        wanted = _emojis_in(text)
        if wanted:
            row = base.filter(Message.emojis.in_(wanted)).order_by(func.random()).first()
            if row:
                return row[0]
        # 2. тон чата → корзина эмодзи
        bucket = _SENTIMENT_EMOJI.get(_recent_chat_sentiment(session, chat_id, cutoff) or "", [])
        if bucket:
            row = base.filter(Message.emojis.in_(bucket)).order_by(func.random()).first()
            if row:
                return row[0]
        # 3. любой недавний
        row = base.order_by(func.random()).first()
        return row[0] if row else None
    finally:
        session.close()