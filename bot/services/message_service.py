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
            emojis="".join([e for e in tg_message.text if emoji.is_emoji(e)]) if tg_message.text else None,
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


def random_recent_sticker(chat_id: int, days: int = 7) -> str | None:
    """Случайный sticker file_id из отправленных в чате за последние `days`
    дней. None, если стикеров нет. Для «мута бота» (/duelbot): бот отвечает
    рандомным недавним стикером вместо болтовни."""
    session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        row = (
            session.query(Message.sticker)
            .filter(
                Message.chat_id == chat_id,
                Message.sticker.isnot(None),
                Message.created_at >= cutoff,
            )
            .order_by(func.random())
            .first()
        )
        return row[0] if row else None
    finally:
        session.close()