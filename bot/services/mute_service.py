"""Мут участника чата для чат-дуэли. Три стратегии по типу проигравшего:

- native  — обычный участник: restrict_chat_member + until_date (Telegram
  снимает сам).
- hard_admin — админ, которого бот может разжаловать (can_be_edited): снимаем
  ВСЕ права + тег, мутим, а права/тег возвращаем полностью через
  tag_service.process_expired_duel_mutes (sweep в scheduler).
- soft    — админ, которого разжаловать нельзя (владелец / назначенный не
  ботом): нативно не замутить, поэтому бот 15 минут удаляет его не-стикерные
  сообщения (DuelMuteMiddleware в handlers/duel.py читает is_soft_muted).

Каждый мут пишется в duel_mute_registry — по нему выдача тега во время мута
уходит в очередь (не снимает мут), а по истечении тег вешается.
"""
import time
from datetime import timedelta

from aiogram import Bot
from aiogram.types import ChatMember, ChatPermissions

from common.logger.logger import get_logger

logger = get_logger(__name__)

# Полный набор админ-прав — что снимаем при муте и что возвращаем после.
# Все они валидны и как атрибуты ChatMemberAdministrator, и как kwargs
# promote_chat_member.
_ADMIN_RIGHT_FIELDS = (
    "is_anonymous",
    "can_manage_chat",
    "can_delete_messages",
    "can_manage_video_chats",
    "can_restrict_members",
    "can_promote_members",
    "can_change_info",
    "can_invite_users",
    "can_post_messages",
    "can_edit_messages",
    "can_pin_messages",
    "can_post_stories",
    "can_edit_stories",
    "can_delete_stories",
    "can_manage_topics",
)

# Софт-мут: (chat_id, tg_id) -> unix-время окончания. In-memory — на рестарте
# теряется (мут снимается раньше), для 15-минутного наказания это приемлемо
# и не бьёт по хот-пути middleware (без БД на каждое сообщение).
_soft_muted: dict[tuple[int, int], float] = {}


def soft_mute(chat_id: int, tg_id: int, minutes: int) -> None:
    _soft_muted[(chat_id, tg_id)] = time.time() + minutes * 60


def is_soft_muted(chat_id: int, tg_id: int) -> bool:
    until = _soft_muted.get((chat_id, tg_id))
    if until is None:
        return False
    if time.time() >= until:
        _soft_muted.pop((chat_id, tg_id), None)
        return False
    return True


def capture_admin_rights(member: ChatMember) -> dict:
    """Снимок текущих админ-прав (только заданные поля) для точного возврата."""
    return {
        f: bool(getattr(member, f))
        for f in _ADMIN_RIGHT_FIELDS
        if getattr(member, f, None) is not None
    }


def mute_strategy(member: ChatMember | None) -> str:
    """'native' | 'hard_admin' | 'soft' | 'absent' | 'bot'."""
    if member is None or member.status in ("left", "kicked"):
        return "absent"
    if member.user and member.user.is_bot:
        return "bot"
    if member.status == "administrator":
        return "hard_admin" if getattr(member, "can_be_edited", False) else "soft"
    if member.status == "creator":
        return "soft"  # владельца не разжаловать
    return "native"  # обычный участник (в т.ч. уже restricted — до-ограничим)


def is_already_muted(chat_id: int, member: ChatMember | None) -> bool:
    if member is None:
        return False
    tg = member.user.id if member.user else None
    if tg is not None:
        from services import duel_mute_registry as reg

        if is_soft_muted(chat_id, tg) or reg.is_muted_now(chat_id, tg):
            return True
    return member.status == "restricted" and getattr(member, "can_send_messages", True) is False


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
    """Замутить проигравшего на `minutes` минут (только стикеры) по стратегии.

    Каждый мут пишется в duel_mute_registry — по нему выдача тегов уходит в
    очередь (тег не снимает мут), а по истечении применяется отложенный тег /
    возвращаются права (tag_service.process_expired_duel_mutes)."""
    from services import duel_mute_registry as reg

    until = int(time.time()) + minutes * 60
    strat = mute_strategy(member)
    if strat == "soft":
        soft_mute(chat_id, tg_id, minutes)
        reg.set_mute(chat_id, tg_id, until, "soft")
        return True, None
    if strat == "hard_admin":
        from services.tag_service import clear_title, restore_admin_now

        title = (getattr(member, "custom_title", None) or "").strip()
        rights = capture_admin_rights(member)
        ok, err = await clear_title(bot, chat_id, tg_id)  # демоут + снять title
        if not ok:
            return False, f"демоут не удался: {err}"
        # Запись мута ДО restrict: если процесс упадёт между демоутом и restrict,
        # sweep всё равно вернёт права (человек не застрянет разжалованным).
        reg.set_mute(chat_id, tg_id, until, "hard_admin", title=title, rights=rights)
        ok, err = await _restrict(bot, chat_id, tg_id, minutes)
        if not ok:
            reg.clear_mute(chat_id, tg_id)
            await restore_admin_now(bot, chat_id, tg_id, rights, title)
            return False, err
        return True, None
    # native (обычный участник)
    ok, err = await _restrict(bot, chat_id, tg_id, minutes)
    if ok:
        reg.set_mute(chat_id, tg_id, until, "native")
    return ok, err


def _open_permissions() -> ChatPermissions:
    """Вернуть обычные права участника (снять мут)."""
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_change_info=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


async def unmute_now(bot: Bot, chat_id: int, tg_id: int) -> tuple[bool, str | None]:
    """Снять дуэль-мут досрочно (ручной /unmute). Возвращает права/тег как
    при обычном истечении. (False, 'не в муте') если человек не замучен."""
    from services import duel_mute_registry as reg
    from services.tag_rental_service import active_title_for_tg
    from services.tag_service import restore_admin_now, set_title

    mute = reg.get_mute(chat_id, tg_id)
    was_soft = is_soft_muted(chat_id, tg_id)
    if not mute and not was_soft:
        return False, "не в муте"

    pending = reg.pending_tag(chat_id, tg_id)
    kind = (mute or {}).get("kind", "soft" if was_soft else "native")
    rights = (mute or {}).get("rights") or {}
    saved_title = (mute or {}).get("title") or ""

    try:
        if kind == "hard_admin" and rights:
            # промоут сам снимает restrict; чистим реестр только при успехе
            title = pending or active_title_for_tg(chat_id, tg_id) or saved_title
            ok, err = await restore_admin_now(bot, chat_id, tg_id, rights, title)
            if not ok:
                return False, err
            reg.clear_mute(chat_id, tg_id)
            reg.clear_pending_tag(chat_id, tg_id)
            return True, None

        if kind == "native":
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=tg_id,
                permissions=_open_permissions(),
                use_independent_chat_permissions=True,
            )
        # снимаем состояние ДО set_title, иначе тег снова уйдёт в очередь
        reg.clear_mute(chat_id, tg_id)
        reg.clear_pending_tag(chat_id, tg_id)
        _soft_muted.pop((chat_id, tg_id), None)
        if pending:
            await set_title(bot, chat_id, tg_id, pending)
        return True, None
    except Exception as exc:
        return False, str(exc)


async def member_status(bot: Bot, chat_id: int, tg_id: int) -> ChatMember | None:
    """get_chat_member или None при ошибке (юзер не в чате и т.п.)."""
    try:
        return await bot.get_chat_member(chat_id=chat_id, user_id=tg_id)
    except Exception as exc:
        logger.warning("get_chat_member failed chat=%s user=%s: %s", chat_id, tg_id, exc)
        return None


async def bot_admin_rights(bot: Bot, chat_id: int) -> ChatMember | None:
    """Член-объект бота, если он админ (для чтения can_restrict/promote/delete)."""
    me = await bot.get_me()
    member = await member_status(bot, chat_id, me.id)
    if member is None or member.status != "administrator":
        return None
    return member
