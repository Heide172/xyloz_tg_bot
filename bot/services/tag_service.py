"""Управление Telegram custom_title (подпись у ника в чате).

Telegram ставит custom_title только админам и максимум 16 символов.
Поэтому: promote с безобидным правом → setChatAdministratorCustomTitle.
Снятие = promote со всеми правами False (demote).

Используется для авто-тега номинантам (пидор дня и т.п.) и рынка
аренды тегов.
"""
from datetime import datetime

from aiogram import Bot

from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting

logger = get_logger(__name__)

TITLE_MAX = 16


def _ensure_table() -> None:
    BotSetting.__table__.create(bind=engine, checkfirst=True)


def _setting_get(key: str) -> str | None:
    _ensure_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == key).first()
        return row.value if row else None
    finally:
        s.close()


def _setting_set(key: str, value: str) -> None:
    _ensure_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == key).first()
        if row:
            row.value = value
        else:
            s.add(BotSetting(key=key, value=value))
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


async def set_title(bot: Bot, chat_id: int, tg_user_id: int, title: str) -> bool:
    """Назначить custom_title. True если удалось."""
    title = (title or "").strip()[:TITLE_MAX]
    if not title:
        return False
    try:
        await bot.promote_chat_member(
            chat_id=chat_id,
            user_id=tg_user_id,
            can_invite_users=True,  # минимальное право, чтобы стать админом
            can_manage_chat=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_pin_messages=False,
        )
        await bot.set_chat_administrator_custom_title(
            chat_id=chat_id, user_id=tg_user_id, custom_title=title
        )
        return True
    except Exception as exc:
        logger.warning("set_title failed chat=%s user=%s: %s", chat_id, tg_user_id, exc)
        return False


async def clear_title(bot: Bot, chat_id: int, tg_user_id: int) -> bool:
    """Снять тег = demote (все права False)."""
    try:
        await bot.promote_chat_member(
            chat_id=chat_id,
            user_id=tg_user_id,
            can_invite_users=False,
            can_manage_chat=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_pin_messages=False,
        )
        return True
    except Exception as exc:
        logger.warning("clear_title failed chat=%s user=%s: %s", chat_id, tg_user_id, exc)
        return False


# ---------------- авто-тег номинантам ----------------


async def assign_nomination_tag(
    bot: Bot, chat_id: int, tg_user_id: int, title: str, slot: str
) -> None:
    """Повесить тег номинанту, сняв его с предыдущего держателя этого слота.

    slot — ключ номинации ('fag', 'active', ...). Трекаем последнего
    держателя в BotSetting, чтобы не оставлять старые теги навечно.

    Не трогаем юзеров с активной арендой тега (они заплатили) —
    проверка делается вызывающей стороной при наличии rental-сервиса.
    """
    key = f"nomtag:{slot}:{chat_id}"
    prev = _setting_get(key)
    if prev:
        try:
            prev_id = int(prev)
            if prev_id != tg_user_id:
                await clear_title(bot, chat_id, prev_id)
        except ValueError:
            pass
    ok = await set_title(bot, chat_id, tg_user_id, title)
    if ok:
        _setting_set(key, str(tg_user_id))
