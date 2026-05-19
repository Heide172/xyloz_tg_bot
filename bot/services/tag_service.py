"""Управление Telegram custom_title (подпись у ника в чате).

Telegram ставит custom_title только админам и максимум 16 символов.
Поэтому: promote с безобидным правом → setChatAdministratorCustomTitle.
Снятие = promote со всеми правами False (demote).

Используется для авто-тега номинантам (пидор дня и т.п.) и рынка
аренды тегов.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting

logger = get_logger(__name__)

TITLE_MAX = 16
MSK = ZoneInfo("Europe/Moscow")


def _today_msk() -> str:
    return datetime.now(tz=MSK).date().isoformat()


def _parse_holder(value: str | None) -> tuple[int | None, str | None]:
    """nomtag-значение: 'tg_id' (старый формат) или 'tg_id:YYYY-MM-DD'."""
    if not value:
        return None, None
    parts = value.split(":", 1)
    try:
        tg_id = int(parts[0])
    except ValueError:
        return None, None
    day = parts[1] if len(parts) > 1 else None
    return tg_id, day


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


def _setting_delete(key: str) -> None:
    _ensure_table()
    s = SessionLocal()
    try:
        s.query(BotSetting).filter(BotSetting.key == key).delete()
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _settings_with_prefix(prefix: str) -> list[tuple[str, str]]:
    _ensure_table()
    s = SessionLocal()
    try:
        rows = (
            s.query(BotSetting)
            .filter(BotSetting.key.like(prefix + "%"))
            .all()
        )
        return [(r.key, r.value) for r in rows]
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
    prev_id, _prev_day = _parse_holder(_setting_get(key))
    if prev_id is not None and prev_id != tg_user_id:
        # Номинант перетирал арендный тег у prev — вернём его, если
        # аренда ещё активна; иначе просто снимаем (demote).
        from services.tag_rental_service import active_title_for_tg

        rented = active_title_for_tg(chat_id, prev_id)
        if rented:
            await set_title(bot, chat_id, prev_id, rented)
        else:
            await clear_title(bot, chat_id, prev_id)
    # Приоритет всегда у номинанта — перетираем любой тег нового держателя.
    ok = await set_title(bot, chat_id, tg_user_id, title)
    if ok:
        _setting_set(key, f"{tg_user_id}:{_today_msk()}")


async def expire_nomination_tags(bot: Bot) -> int:
    """Снять протухшие номинант-теги (день MSK < сегодня или старый
    формат без даты). Если у держателя активная аренда — вернуть
    арендный тег. Возвращает число снятых. Вызывается планировщиком.
    """
    today = _today_msk()
    cleared = 0
    for key, value in _settings_with_prefix("nomtag:"):
        tg_id, day = _parse_holder(value)
        if tg_id is None:
            _setting_delete(key)
            continue
        if day == today:
            continue  # тег за сегодня — не трогаем
        parts = key.split(":")
        if len(parts) != 3:
            continue
        try:
            chat_id = int(parts[2])
        except ValueError:
            continue
        from services.tag_rental_service import active_title_for_tg

        rented = active_title_for_tg(chat_id, tg_id)
        try:
            if rented:
                await set_title(bot, chat_id, tg_id, rented)
            else:
                await clear_title(bot, chat_id, tg_id)
            _setting_delete(key)
            cleared += 1
        except Exception:
            logger.warning(
                "expire nomtag failed key=%s tg=%s", key, tg_id
            )
    if cleared:
        logger.info("nomination tags expired: %d", cleared)
    return cleared
