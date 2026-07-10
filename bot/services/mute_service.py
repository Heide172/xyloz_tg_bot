"""Мут участника чата для чат-дуэли.

Обычного участника мутим нативно (restrict_chat_member + until_date —
Telegram снимает ограничение сам).

Тег-админа замутить нативно нельзя: механика тегов (tag_service) делает
держателя тега настоящим Telegram-админом (promote + custom_title), а
Telegram запрещает restrict на админов. Поэтому такого сначала демоутим
(тег слетает), мутим, а тег возвращаем позже через
tag_service.restore_due_duel_tags (sweep в scheduler).
"""
import time
from datetime import timedelta

from aiogram import Bot
from aiogram.types import ChatMember, ChatPermissions

from common.logger.logger import get_logger

logger = get_logger(__name__)

# Реальные админ-права. Механика тегов (tag_service.set_title) выдаёт только
# can_invite_users; если у редактируемого нами админа нет ни одного из этих
# прав — это «тег-админ» (косметика), а не модератор.
_REAL_ADMIN_POWERS = (
    "can_manage_chat",
    "can_delete_messages",
    "can_restrict_members",
    "can_promote_members",
    "can_change_info",
    "can_pin_messages",
    "can_post_messages",
    "can_edit_messages",
    "can_manage_topics",
    "can_manage_video_chats",
    "can_post_stories",
    "can_edit_stories",
    "can_delete_stories",
)


def is_tag_admin(member: ChatMember | None) -> bool:
    """Админ, которого бот назначил только ради тега (custom_title)?

    Признаки: статус administrator, его можно редактировать нами
    (can_be_edited — значит промоутил бот), и нет ни одного реального
    админ-права.
    """
    if member is None or member.status != "administrator":
        return False
    if not getattr(member, "can_be_edited", False):
        return False
    return not any(getattr(member, p, False) for p in _REAL_ADMIN_POWERS)


def mute_block_reason(member: ChatMember | None) -> str | None:
    """None — участника можно замутить. Иначе код причины:
    absent | bot | owner | real_admin | muted."""
    if member is None or member.status in ("left", "kicked"):
        return "absent"
    if member.user and member.user.is_bot:
        return "bot"
    if member.status == "creator":
        return "owner"
    if member.status == "administrator" and not is_tag_admin(member):
        return "real_admin"
    if member.status == "restricted" and getattr(member, "can_send_messages", True) is False:
        return "muted"
    return None


def _stickers_only_permissions() -> ChatPermissions:
    """Только стикеры/GIF/inline (can_send_other_messages), остальное — нет.

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


async def _restrict(bot: Bot, chat_id: int, tg_id: int, minutes: int) -> tuple[bool, str | None]:
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
        logger.error("restrict failed chat=%s user=%s: %s", chat_id, tg_id, msg)
        return False, msg


async def apply_duel_mute(
    bot: Bot, chat_id: int, tg_id: int, minutes: int, member: ChatMember | None
) -> tuple[bool, str | None]:
    """Замутить проигравшего на `minutes` минут (только стикеры).

    Тег-админа: снять тег + демоут → restrict → запомнить тег на возврат.
    Обычного участника — сразу restrict (Telegram снимет по until_date).
    """
    if is_tag_admin(member):
        from services.tag_service import clear_title, remember_duel_tag_restore

        title = (getattr(member, "custom_title", None) or "").strip()
        ok, err = await clear_title(bot, chat_id, tg_id)  # demote + снять title
        if not ok:
            return False, f"демоут не удался: {err}"
        ok, err = await _restrict(bot, chat_id, tg_id, minutes)
        if not ok:
            # мут не встал — возвращаем тег, чтобы не оставить человека без него
            if title:
                await _rollback_title(bot, chat_id, tg_id, title)
            return False, err
        until = int(time.time()) + minutes * 60
        remember_duel_tag_restore(chat_id, tg_id, until, title)
        return True, None
    return await _restrict(bot, chat_id, tg_id, minutes)


async def _rollback_title(bot: Bot, chat_id: int, tg_id: int, title: str) -> None:
    from services.tag_service import set_title

    try:
        await set_title(bot, chat_id, tg_id, title)
    except Exception:
        logger.exception("rollback set_title failed chat=%s tg=%s", chat_id, tg_id)


async def member_status(bot: Bot, chat_id: int, tg_id: int) -> ChatMember | None:
    """get_chat_member или None при ошибке (юзер не в чате и т.п.)."""
    try:
        return await bot.get_chat_member(chat_id=chat_id, user_id=tg_id)
    except Exception as exc:
        logger.warning("get_chat_member failed chat=%s user=%s: %s", chat_id, tg_id, exc)
        return None


async def bot_admin_rights(bot: Bot, chat_id: int) -> ChatMember | None:
    """Член-объект бота, если он админ (для чтения can_restrict/can_promote); иначе None."""
    me = await bot.get_me()
    member = await member_status(bot, chat_id, me.id)
    if member is None or member.status != "administrator":
        return None
    return member
