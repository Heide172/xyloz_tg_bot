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


async def set_title(
    bot: Bot, chat_id: int, tg_user_id: int, title: str
) -> tuple[bool, str | None]:
    """Назначить custom_title. Возвращает (ok, error_text).

    Если человек сейчас в дуэль-муте — тег НЕ вешаем (promote снял бы мут),
    а кладём в очередь; повесит process_expired_duel_mutes после мута."""
    title = (title or "").strip()[:TITLE_MAX]
    if not title:
        return False, "пустой title"
    from services import duel_mute_registry as reg

    if reg.is_muted_now(chat_id, tg_user_id):
        reg.queue_tag(chat_id, tg_user_id, title)
        logger.info("tag queued behind duel-mute chat=%s tg=%s", chat_id, tg_user_id)
        return True, None
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
        return True, None
    except Exception as exc:
        msg = str(exc)
        logger.error(
            "set_title failed chat=%s user=%s: %s", chat_id, tg_user_id, msg
        )
        return False, msg


async def clear_title(
    bot: Bot, chat_id: int, tg_user_id: int
) -> tuple[bool, str | None]:
    """Снять Telegram custom_title и demote. Возвращает (ok, error_text).

    Двухшаговая последовательность: сначала setChatAdministratorCustomTitle("")
    (пока юзер ещё админ), потом promote(... все права False).
    Без явной зануляния title клиенты Telegram могут оставлять старый
    custom_title в кэше, видный другим участникам чата.
    """
    try:
        await bot.set_chat_administrator_custom_title(
            chat_id=chat_id, user_id=tg_user_id, custom_title=""
        )
    except Exception as exc:
        # Не критично — юзер мог быть promoted не нами; продолжаем demote.
        logger.warning(
            "clear: setTitle('') failed chat=%s user=%s: %s (продолжаем demote)",
            chat_id, tg_user_id, exc,
        )
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
        return True, None
    except Exception as exc:
        msg = str(exc)
        logger.error(
            "clear_title failed chat=%s user=%s: %s", chat_id, tg_user_id, msg
        )
        return False, msg


# ---------------- авто-тег номинантам ----------------


async def assign_nomination_tag(
    bot: Bot, chat_id: int, tg_user_id: int, title: str, slot: str
) -> None:
    """Повесить тег номинанту, сняв его с предыдущего держателя этого слота.

    slot — ключ номинации ('fag', 'active', ...). Трекаем последнего
    держателя в BotSetting, чтобы не оставлять старые теги навечно.

    Если у нового номинанта активная аренда — продлеваем её на 1 день
    (компенсация за день, который ему придётся ходить с тегом номинанта).
    Через сутки expire_nomination_tags снимет номинант и вернёт арендный.
    """
    from services.tag_rental_service import (
        active_title_for_tg,
        extend_rental_after_nomination,
    )

    key = f"nomtag:{slot}:{chat_id}"
    prev_id, _prev_day = _parse_holder(_setting_get(key))
    if prev_id is not None and prev_id != tg_user_id:
        # Номинант перетирал арендный тег у prev — вернём его, если
        # аренда ещё активна; иначе просто снимаем (demote).
        rented = active_title_for_tg(chat_id, prev_id)
        if rented:
            await set_title(bot, chat_id, prev_id, rented)
        else:
            await clear_title(bot, chat_id, prev_id)
    # Если у нового номинанта активная аренда — компенсируем +1 день.
    # Делаем ДО set_title чтобы при сбое не потерять компенсацию.
    if active_title_for_tg(chat_id, tg_user_id):
        ext = extend_rental_after_nomination(chat_id, tg_user_id, days=1)
        if ext.get("extended"):
            logger.info(
                "nomtag %s: extended rental for tg=%s («%s» → %s)",
                slot, tg_user_id, ext["title"], ext["new_expires_at"],
            )
    # Приоритет всегда у номинанта — перетираем любой тег нового держателя.
    ok, err = await set_title(bot, chat_id, tg_user_id, title)
    if ok:
        _setting_set(key, f"{tg_user_id}:{_today_msk()}")
    else:
        logger.error(
            "nomtag %s: set_title failed for tg=%s: %s", slot, tg_user_id, err
        )


async def expire_nomination_tags(bot: Bot) -> int:
    """Снять протухшие номинант-теги (день MSK < сегодня или старый
    формат без даты). Если у держателя активная аренда — вернуть
    арендный тег. Возвращает число снятых.

    Если Telegram отказал (set/clear_title вернули False) — ключ НЕ удаляем,
    чтобы следующий тик повторил попытку. Раньше ключ удалялся всегда —
    из-за чего тег оставался в чате навсегда при первом же сбое.
    """
    from services.tag_rental_service import active_title_for_tg

    today = _today_msk()
    cleared = 0
    failed = 0
    for key, value in _settings_with_prefix("nomtag:"):
        tg_id, day = _parse_holder(value)
        if tg_id is None:
            _setting_delete(key)
            continue
        if day == today:
            continue  # тег за сегодня — не трогаем
        parts = key.split(":")
        if len(parts) != 3:
            _setting_delete(key)  # сломанный ключ — выкидываем
            continue
        try:
            chat_id = int(parts[2])
        except ValueError:
            _setting_delete(key)
            continue

        rented = active_title_for_tg(chat_id, tg_id)
        if rented:
            ok, err = await set_title(bot, chat_id, tg_id, rented)
        else:
            ok, err = await clear_title(bot, chat_id, tg_id)
        if ok:
            _setting_delete(key)
            cleared += 1
        else:
            failed += 1
            logger.error(
                "nomtag expire FAILED key=%s tg=%s chat=%s: %s (retry next tick)",
                key, tg_id, chat_id, err,
            )
    if cleared or failed:
        logger.info(
            "nomination tags expired: ok=%d failed=%d (failed keys остаются для retry)",
            cleared, failed,
        )
    return cleared


# ---------------- истечение дуэль-мута: возврат прав + отложенный тег --------


async def restore_admin_now(
    bot: Bot, chat_id: int, tg_id: int, rights: dict, title: str
) -> tuple[bool, str | None]:
    """Вернуть админ-права (promote) и custom_title. Возвращает (ok, error)."""
    try:
        await bot.promote_chat_member(chat_id=chat_id, user_id=tg_id, **rights)
        if title:
            await bot.set_chat_administrator_custom_title(
                chat_id=chat_id, user_id=tg_id, custom_title=title[:TITLE_MAX]
            )
        return True, None
    except Exception as exc:
        msg = str(exc)
        logger.error("restore_admin failed chat=%s tg=%s: %s", chat_id, tg_id, msg)
        return False, msg


async def process_expired_duel_mutes(bot: Bot) -> int:
    """Для тех, чей дуэль-мут истёк (until <= now): само ограничение снял
    Telegram по until_date; тут возвращаем права тег-админам и вешаем тег,
    отложенный в очередь во время мута (аренда/номинация). Приоритет титула:
    очередь > активная аренда > старый. При сбое запись НЕ чистим — повторим.
    """
    import time

    from services import duel_mute_registry as reg
    from services.tag_rental_service import active_title_for_tg

    now = int(time.time())
    done = 0
    failed = 0
    for chat_id, tg_id, mute in reg.iter_mutes():
        if mute["until"] > now:
            continue  # мут ещё идёт

        pending = reg.pending_tag(chat_id, tg_id)
        rights = mute.get("rights") or {}
        try:
            if mute.get("kind") == "hard_admin" and rights:
                # вернуть полные права; титул — очередь > аренда > сохранённый
                title = pending or active_title_for_tg(chat_id, tg_id) or mute.get("title") or ""
                ok, err = await restore_admin_now(bot, chat_id, tg_id, rights, title)
            elif pending:
                # обычному участнику тег клали в очередь во время мута — вешаем
                ok, err = await set_title(bot, chat_id, tg_id, pending)
            else:
                ok, err = True, None  # native без тега — Telegram уже всё снял
        except Exception as exc:
            ok, err = False, str(exc)

        if ok:
            reg.clear_mute(chat_id, tg_id)
            reg.clear_pending_tag(chat_id, tg_id)
            done += 1
        else:
            failed += 1
            logger.error(
                "duel mute expiry apply FAILED chat=%s tg=%s: %s (retry next tick)",
                chat_id, tg_id, err,
            )
    if done or failed:
        logger.info("duel mute expiry: ok=%d failed=%d", done, failed)
    return done
