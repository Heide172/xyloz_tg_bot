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


def _tg(method: str, params: dict) -> bool:
    url = f"https://api.telegram.org/bot{_bot_token()}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"User-Agent": "xyloz-bot-api/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            logger.warning("%s failed: %s", method, body)
            return False
        return True
    except Exception:
        logger.exception("%s error", method)
        return False


def _set_tg_title(chat_id: int, tg_user_id: int, title: str) -> bool:
    ok = _tg("promoteChatMember", {
        "chat_id": chat_id, "user_id": tg_user_id, "can_invite_users": "true"
    })
    if not ok:
        return False
    return _tg("setChatAdministratorCustomTitle", {
        "chat_id": chat_id, "user_id": tg_user_id, "custom_title": title[:TITLE_MAX]
    })


def _clear_tg_title(chat_id: int, tg_user_id: int) -> bool:
    return _tg("promoteChatMember", {
        "chat_id": chat_id, "user_id": tg_user_id, "can_invite_users": "false"
    })


def quote(days: int) -> int:
    if days not in ALLOWED_DAYS:
        raise InvalidArgument(f"Срок: один из {ALLOWED_DAYS} дней")
    return RENT_PER_DAY * days


def rent_sync(
    user_id: int, tg_user_id: int, chat_id: int, title: str, days: int
) -> dict:
    title = (title or "").strip()
    if not (1 <= len(title) <= TITLE_MAX):
        raise InvalidArgument(f"Тег: 1..{TITLE_MAX} символов")
    price = quote(days)
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        # title занят другим активным арендатором?
        busy = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.title == title,
                TagRental.user_id != user_id,
            )
            .first()
        )
        if busy:
            raise InvalidArgument("Этот тег уже арендован другим игроком")
        # у юзера уже активный?
        mine = (
            session.query(TagRental)
            .filter(
                TagRental.chat_id == chat_id,
                TagRental.status == "active",
                TagRental.user_id == user_id,
            )
            .with_for_update()
            .first()
        )
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < price:
            raise InsufficientFunds(f"Нужно {price}, у тебя {bal.balance}")
        bank = _get_or_create_bank(session, chat_id)
        bal.balance -= price
        bal.updated_at = now
        bank.balance += price
        bank.updated_at = now
        _log_tx(session, user_id, chat_id, -price,
                kind="tag_rent", note=f"«{title}» на {days}д")
        _log_tx(session, None, chat_id, price, kind="tag_rent_to_bank",
                note=f"«{title}»")

        if mine:
            # продление/замена: новый title и срок поверх старого
            mine.title = title
            mine.expires_at = now + timedelta(days=days)
            mine.price_paid += price
            rental = mine
        else:
            rental = TagRental(
                chat_id=chat_id,
                user_id=user_id,
                tg_user_id=tg_user_id,
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
        }
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    # Telegram-вызов вне транзакции
    _set_tg_title(chat_id, tg_user_id, title)
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
    _clear_tg_title(chat_id, tg_id)
    return {"ok": True}


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
    for chat_id, tg_id in targets:
        _clear_tg_title(chat_id, tg_id)
    if targets:
        logger.info("tag rentals expired: %d", len(targets))
    return len(targets)
