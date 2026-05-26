"""Рынок аренды кастомных Telegram-тегов.

Аренда на N дней за гривны (→ банк чата, sink). Один активный title на
чат (уникальность по тексту), один активный rental на юзера. По
истечении scheduler снимает Telegram custom_title.

Telegram-вызовы — напрямую через Bot API (urllib), т.к. сервис
используется и из API-контейнера (без aiogram Bot).
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.tag_rental import TagRental
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)

TITLE_MAX = 16
RENT_PER_DAY = int(os.getenv("TAG_RENT_PER_DAY", "500"))
ALLOWED_DAYS = [1, 3, 7]


def _bot_token() -> str:
    t = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    return t


def _humanize_tg_error(method: str, code: int | None, desc: str) -> str:
    """Превращает Telegram error в понятный пользователю текст."""
    d = (desc or "").lower()
    if "not enough rights" in d or "can't promote" in d or "can_promote_members" in d:
        return "У бота нет прав admin'а в чате — попроси админа выдать боту право назначать админов."
    if "user is an administrator of the chat" in d or "method is available only for supergroups" in d:
        return desc or "Telegram отказал в операции."
    if "user_not_promoted" in d or "can't change custom title" in d or (
        "not enough rights" in d and method == "setChatAdministratorCustomTitle"
    ):
        return "Telegram разрешает менять тег только тем, кого бот сам сделал админом. Если ты уже админ — попроси владельца снять с тебя админку и попробуй снова."
    if "chat_admin_required" in d:
        return "Бот не админ в этом чате — теги недоступны."
    if "user not found" in d:
        return "Юзер не найден в чате."
    if code:
        return f"Telegram error {code}: {desc}"
    return desc or "Telegram не ответил."


def _tg(method: str, params: dict) -> tuple[bool, str | None]:
    """Telegram API call. Возвращает (ok, human_error)."""
    url = f"https://api.telegram.org/bot{_bot_token()}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"User-Agent": "xyloz-bot-api/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.request.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            logger.error("%s HTTPError %s (no body)", method, exc.code)
            return False, f"Telegram HTTP {exc.code}"
    except Exception:
        logger.exception("%s network error", method)
        return False, "Сеть недоступна, попробуй позже."

    if body.get("ok"):
        return True, None
    code = body.get("error_code")
    desc = body.get("description") or ""
    logger.error("%s failed: code=%s desc=%s", method, code, desc)
    return False, _humanize_tg_error(method, code, desc)


def _set_tg_title(chat_id: int, tg_user_id: int, title: str) -> tuple[bool, str | None]:
    ok, err = _tg("promoteChatMember", {
        "chat_id": chat_id, "user_id": tg_user_id, "can_invite_users": "true"
    })
    if not ok:
        return False, err
    return _tg("setChatAdministratorCustomTitle", {
        "chat_id": chat_id, "user_id": tg_user_id, "custom_title": title[:TITLE_MAX]
    })


def _clear_tg_title(chat_id: int, tg_user_id: int) -> tuple[bool, str | None]:
    return _tg("promoteChatMember", {
        "chat_id": chat_id, "user_id": tg_user_id, "can_invite_users": "false"
    })


def quote(days: int) -> int:
    if days not in ALLOWED_DAYS:
        raise InvalidArgument(f"Срок: один из {ALLOWED_DAYS} дней")
    return RENT_PER_DAY * days


def rent_sync(
    payer_user_id: int,
    payer_tg_id: int,
    chat_id: int,
    title: str,
    days: int,
    recipient_user_id: int | None = None,
    recipient_tg_id: int | None = None,
) -> dict:
    """Купить/продлить тег. Получатель = payer, либо явный recipient (подарок)."""
    title = (title or "").strip()
    if not (1 <= len(title) <= TITLE_MAX):
        raise InvalidArgument(f"Тег: 1..{TITLE_MAX} символов")
    price = quote(days)

    holder_user_id = recipient_user_id if recipient_user_id is not None else payer_user_id
    holder_tg_id = recipient_tg_id if recipient_tg_id is not None else payer_tg_id
    is_gift = recipient_user_id is not None and recipient_user_id != payer_user_id

    session = SessionLocal()
    try:
        now = datetime.utcnow()
        # title занят другим активным арендатором (не получателем)?
        busy = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.title == title,
                TagRental.user_id != holder_user_id,
            )
            .first()
        )
        if busy:
            raise InvalidArgument("Этот тег уже арендован другим игроком")
        # у получателя уже активный?
        mine = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.user_id == holder_user_id,
            )
            .with_for_update()
            .first()
        )
        bal = _get_or_create_balance(session, payer_user_id, chat_id)
        if bal.balance < price:
            raise InsufficientFunds(f"Нужно {price}, у тебя {bal.balance}")
        bank = _get_or_create_bank(session, chat_id)
        bal.balance -= price
        bal.updated_at = now
        bank.balance += price
        bank.updated_at = now
        gift_note = f" (подарок→{holder_tg_id})" if is_gift else ""
        _log_tx(session, payer_user_id, chat_id, -price,
                kind="tag_rent", note=f"«{title}» на {days}д{gift_note}")
        _log_tx(session, None, chat_id, price, kind="tag_rent_to_bank",
                note=f"«{title}»")

        if mine:
            # продление/замена: новый title и срок поверх старого
            mine.title = title
            mine.expires_at = now + timedelta(days=days)
            mine.price_paid += price
            mine.tg_user_id = holder_tg_id  # на всякий — синхронизируем
            rental = mine
        else:
            rental = TagRental(
                chat_id=chat_id,
                user_id=holder_user_id,
                tg_user_id=holder_tg_id,
                title=title,
                price_paid=price,
                rented_at=now,
                expires_at=now + timedelta(days=days),
                status="active",
            )
            session.add(rental)
        session.flush()
        result = {
            "title": title,
            "expires_at": rental.expires_at.isoformat(),
            "price": price,
            "user_balance": bal.balance,
            "gift": is_gift,
            "recipient_tg_id": holder_tg_id if is_gift else None,
        }
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    # Telegram-вызов вне транзакции
    tg_ok, tg_err = _set_tg_title(chat_id, holder_tg_id, title)
    result["tg_applied"] = tg_ok
    result["tg_error"] = tg_err
    return result


def cancel_sync(user_id: int, chat_id: int) -> dict:
    session = SessionLocal()
    try:
        r = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.user_id == user_id,
            )
            .with_for_update()
            .first()
        )
        if not r:
            raise InvalidArgument("У тебя нет активного тега")
        r.status = "cancelled"
        tg_id = int(r.tg_user_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    tg_ok, tg_err = _clear_tg_title(chat_id, tg_id)
    return {"ok": True, "tg_applied": tg_ok, "tg_error": tg_err}


def reapply_sync(user_id: int, chat_id: int) -> dict:
    """Повторно выставить Telegram-тег по активной аренде без списания.
    Полезно если предыдущий вызов TG провалился (бот лишился прав)."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        r = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.user_id == user_id,
                TagRental.expires_at > now,
            )
            .order_by(TagRental.expires_at.desc())
            .first()
        )
        if not r:
            raise InvalidArgument("Нет активной аренды для повтора")
        title = r.title
        tg_id = int(r.tg_user_id)
    finally:
        session.close()
    tg_ok, tg_err = _set_tg_title(chat_id, tg_id, title)
    return {"ok": True, "title": title, "tg_applied": tg_ok, "tg_error": tg_err}


def state_sync(user_id: int, chat_id: int) -> dict:
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        mine = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.user_id == user_id,
            )
            .first()
        )
        occupied = (
            session.query(TagRental.title)
            .filter(TagRental.chat_id == chat_id, TagRental.status == "active")
            .all()
        )
        return {
            "per_day": RENT_PER_DAY,
            "allowed_days": ALLOWED_DAYS,
            "max_len": TITLE_MAX,
            "mine": (
                {
                    "title": mine.title,
                    "expires_at": mine.expires_at.isoformat(),
                    "expired": mine.expires_at < now,
                }
                if mine
                else None
            ),
            "occupied": sorted({t[0] for t in occupied}),
        }
    finally:
        session.close()


def extend_rental_after_nomination(
    chat_id: int, tg_user_id: int, days: int = 1
) -> dict:
    """Продлить активную аренду на N дней (компенсация за день под номинант-тегом).

    Возвращает {extended, title, new_expires_at}. Если активной аренды нет —
    {extended: False}. Идемпотентность сейчас не нужна (вызов раз в день из
    assign_nomination_tag), но если потребуется — можно завести табличку
    rental_extensions(date, slot, chat_id, user_id) и пропускать дубль.
    """
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        r = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.tg_user_id == tg_user_id,
                TagRental.status == "active",
                TagRental.expires_at > now,
            )
            .order_by(TagRental.expires_at.desc())
            .with_for_update()
            .first()
        )
        if not r:
            return {"extended": False, "title": None, "new_expires_at": None}
        r.expires_at = r.expires_at + timedelta(days=days)
        new_expires = r.expires_at
        title = r.title
        session.commit()
        logger.info(
            "rental extended by %dд for tg=%s chat=%s («%s» → %s)",
            days, tg_user_id, chat_id, title, new_expires.isoformat(),
        )
        return {
            "extended": True,
            "title": title,
            "new_expires_at": new_expires.isoformat(),
        }
    except Exception:
        session.rollback()
        logger.exception(
            "extend_rental failed chat=%s tg=%s", chat_id, tg_user_id
        )
        return {"extended": False, "title": None, "new_expires_at": None}
    finally:
        session.close()


def active_title_for_tg(chat_id: int, tg_user_id: int) -> str | None:
    """Текст активной (не истёкшей) аренды юзера, иначе None.
    Используется номинант-тегами чтобы вернуть арендный тег при смене."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        r = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.tg_user_id == tg_user_id,
                TagRental.status == "active",
                TagRental.expires_at > now,
            )
            .order_by(TagRental.expires_at.desc())
            .first()
        )
        return r.title if r else None
    finally:
        session.close()


def expire_due_sync() -> int:
    """Снять Telegram-теги у истёкших аренд. Возвращает кол-во."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        due = (
            session.query(TagRental)
            .filter(TagRental.status == "active", TagRental.expires_at < now)
            .all()
        )
        targets = [(int(r.chat_id), int(r.tg_user_id)) for r in due]
        for r in due:
            r.status = "expired"
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    failed = 0
    for chat_id, tg_id in targets:
        ok, err = _clear_tg_title(chat_id, tg_id)
        if not ok:
            failed += 1
            logger.warning(
                "expire: failed to clear title chat=%s tg=%s: %s",
                chat_id, tg_id, err,
            )
    if targets:
        logger.info(
            "tag rentals expired: %d (tg-clear failed: %d)", len(targets), failed
        )
    return len(targets)
