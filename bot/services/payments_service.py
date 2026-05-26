"""Telegram Stars донат → конвертация в гривны.

Юзер платит N⭐ → на баланс зачисляется N * STARS_TO_HRYVNIA гривен в
указанный чат. Используется для покупки круток гачи и любых других
платных действий. provider_token пустой (XTR).

Идемпотентность: ref_id = telegram_payment_charge_id (уникален per-charge).
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.economy_tx import EconomyTx
from services.economy_service import _log_tx
from services.markets_service import _get_or_create_balance

logger = get_logger(__name__)

# 1⭐ = STARS_TO_HRYVNIA гривен. По умолчанию = одна крутка гачи
# (GACHA_ROLL_COST=300), но настраивается отдельно.
STARS_TO_HRYVNIA = int(os.getenv("STARS_TO_HRYVNIA", "300"))
STARS_PRODUCT_TITLE = os.getenv(
    "STARS_PRODUCT_TITLE", "Поддержка серверов Бурмалды"
)


def _bot_token() -> str:
    t = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    return t


def _tg_post(method: str, params: dict) -> dict:
    url = f"https://api.telegram.org/bot{_bot_token()}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"User-Agent": "xyloz-bot-api/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_stars_invoice_link(
    user_id: int, chat_id: int, stars: int, purpose: str = "gacha"
) -> str:
    """Создать invoice link для оплаты в Stars. Возвращает URL для openInvoice."""
    if stars <= 0 or stars > 2500:
        raise ValueError("stars: 1..2500")
    payload = json.dumps({
        "u": user_id, "c": chat_id, "s": stars, "p": purpose
    }, separators=(",", ":"))
    hryvnia = stars * STARS_TO_HRYVNIA
    description = (
        f"Зачислю {hryvnia} гривен на твой баланс в этом чате. "
        f"Можно потратить на гачу, теги, ставки и игры."
    )
    body = _tg_post("createInvoiceLink", {
        "title": STARS_PRODUCT_TITLE,
        "description": description,
        "payload": payload,
        "provider_token": "",  # обязательно пустой для XTR
        "currency": "XTR",
        "prices": json.dumps([{"label": f"{stars}⭐", "amount": stars}]),
    })
    if not body.get("ok"):
        logger.error("createInvoiceLink failed: %s", body)
        raise RuntimeError(body.get("description") or "Telegram отказал")
    return body["result"]


def apply_stars_payment(
    user_id: int,
    chat_id: int,
    stars: int,
    charge_id: str,
    purpose: str = "gacha",
) -> dict:
    """Зачислить N*STARS_TO_HRYVNIA гривен. Идемпотентно по charge_id.

    Возвращает {credited: bool, amount: int, balance: int}.
    """
    if stars <= 0:
        return {"credited": False, "amount": 0, "balance": 0, "reason": "no_stars"}
    amount = stars * STARS_TO_HRYVNIA
    session = SessionLocal()
    try:
        # idempotency: уже зачисляли этот charge?
        existing = (
            session.query(EconomyTx)
            .filter(
                EconomyTx.kind == "stars_topup",
                EconomyTx.ref_id == charge_id,
            )
            .first()
        )
        if existing:
            bal = _get_or_create_balance(session, user_id, chat_id)
            return {
                "credited": False,
                "amount": amount,
                "balance": bal.balance,
                "reason": "already_credited",
            }
        bal = _get_or_create_balance(session, user_id, chat_id)
        bal.balance += amount
        bal.updated_at = datetime.utcnow()
        _log_tx(
            session, user_id, chat_id, amount,
            kind="stars_topup", ref_id=charge_id,
            note=f"{stars}⭐ → {amount}г ({purpose})",
        )
        session.commit()
        return {"credited": True, "amount": amount, "balance": bal.balance}
    except Exception:
        session.rollback()
        logger.exception(
            "apply_stars_payment failed user=%s chat=%s stars=%s",
            user_id, chat_id, stars,
        )
        raise
    finally:
        session.close()


def parse_invoice_payload(payload: str) -> dict | None:
    """Распаковать payload созданного выше invoice."""
    try:
        data = json.loads(payload)
        return {
            "user_id": int(data["u"]),
            "chat_id": int(data["c"]),
            "stars": int(data["s"]),
            "purpose": str(data.get("p", "gacha")),
        }
    except Exception:
        return None
