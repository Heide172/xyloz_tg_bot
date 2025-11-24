from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User
from common.models.reaction import Reaction
from common.logger.logger import get_logger
from datetime import datetime
import emoji

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
            created_at=tg_message.date if tg_message.date else datetime.utcnow(),
            edited_at=tg_message.edit_date if tg_message.edit_date else None,        )

        session.add(msg)
        session.commit()
        logger.info(f"Saved message {tg_message.message_id} from user {user.tg_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"DB ERROR: {e}", exc_info=True)
    finally:
        session.close()


def save_reaction(event):
    session = SessionLocal()

    try:
        message_id = event.message_id
        user_id = event.user.id

        # find user
        user = session.query(User).filter_by(tg_id=user_id).first()
        if not user:
            user = User(tg_id=user_id)
            session.add(user)
            session.flush()

        reaction = Reaction(
            message_id=message_id,
            user_id=user.id,
            emoji=event.new_reaction,
        )

        session.add(reaction)
        session.commit()
        logger.info(f"Saved reaction for message {message_id} from user {user_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"DB ERROR: {e}", exc_info=True)
    finally:
        session.close()