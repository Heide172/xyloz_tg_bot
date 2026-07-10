"""Мут участника чата через Telegram restrict_chat_member.

Используется чат-дуэлью (bot/handlers/duel.py): проигравший улетает в мут —
может слать только стикеры. Разморозку делает сам Telegram по until_date,
отдельная джоба не нужна (переживает рестарт бота).
"""
from datetime import timedelta

from aiogram import Bot
from aiogram.types import ChatMember, ChatPermissions

from common.logger.logger import get_logger

logger = get_logger(__name__)


def _stickers_only_permissions() -> ChatPermissions:
    """Только стикеры/GIF/inline (can_send_other_messages), всё остальное — нет.

    can_send_other_messages развязан от can_send_messages только при
    use_independent_chat_permissions=True на вызове restrict_chat_member.
    """
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=True,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )


async def mute_stickers_only(
    bot: Bot, chat_id: int, tg_id: int, minutes: int
) -> tuple[bool, str | None]:
    """Замутить на `minutes` минут (только стикеры). Возвращает (ok, error)."""
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=tg_id,
            permissions=_stickers_only_permissions(),
            use_independent_chat_permissions=True,
            until_date=timedelta(minutes=minutes),
        )
        return True, None
    except Exception as exc:
        msg = str(exc)
        logger.error("mute failed chat=%s user=%s: %s", chat_id, tg_id, msg)
        return False, msg


async def member_status(bot: Bot, chat_id: int, tg_id: int) -> ChatMember | None:
    """get_chat_member или None при ошибке (юзер не в чате и т.п.)."""
    try:
        return await bot.get_chat_member(chat_id=chat_id, user_id=tg_id)
    except Exception as exc:
        logger.warning("get_chat_member failed chat=%s user=%s: %s", chat_id, tg_id, exc)
        return None


async def bot_can_restrict(bot: Bot, chat_id: int) -> bool:
    """Бот — админ с правом ограничивать участников?"""
    me = await bot.get_me()
    member = await member_status(bot, chat_id, me.id)
    if member is None or member.status != "administrator":
        return False
    return bool(getattr(member, "can_restrict_members", False))
