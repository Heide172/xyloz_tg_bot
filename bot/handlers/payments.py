"""Обработка Telegram Stars-платежей: pre_checkout + successful_payment.

ВНИМАНИЕ: этот роутер должен подключаться ДО message_router в bot/main.py,
иначе catch-all из messages.py перехватит апдейты.
"""
from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from common.logger.logger import get_logger
from services.payments_service import (
    STARS_TO_HRYVNIA,
    apply_stars_payment,
    parse_invoice_payload,
)
from services.social_service import send_chat_message

logger = get_logger(__name__)
router = Router()


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery) -> None:
    """Всегда подтверждаем — валидация уже была при createInvoiceLink."""
    try:
        await q.answer(ok=True)
    except Exception:
        logger.exception("pre_checkout_query.answer failed id=%s", q.id)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if not sp:
        return
    payload = parse_invoice_payload(sp.invoice_payload or "")
    if not payload:
        logger.error(
            "successful_payment: bad payload tg_user=%s payload=%r",
            message.from_user.id if message.from_user else None,
            sp.invoice_payload,
        )
        await message.answer(
            "⚠️ Платёж получен, но не удалось его привязать. "
            "Напиши админу — вернём вручную."
        )
        return
    charge_id = (
        sp.telegram_payment_charge_id
        or sp.provider_payment_charge_id
        or f"unknown:{message.message_id}"
    )
    try:
        res = apply_stars_payment(
            user_id=payload["user_id"],
            chat_id=payload["chat_id"],
            stars=payload["stars"],
            charge_id=charge_id,
            purpose=payload["purpose"],
        )
    except Exception:
        logger.exception("apply_stars_payment failed charge=%s", charge_id)
        await message.answer(
            "⚠️ Платёж получен, но при зачислении произошла ошибка. "
            "Напиши админу — разберёмся."
        )
        return

    if res.get("credited"):
        await message.answer(
            f"✅ Спасибо за поддержку! Зачислено {res['amount']}г "
            f"({payload['stars']}⭐ × {STARS_TO_HRYVNIA}г). "
            f"Баланс в чате: {res['balance']}г."
        )
        # Дополнительно — сообщение в исходный чат, что юзер задонатил,
        # без указания суммы (тактичность).
        try:
            who = (
                "@" + message.from_user.username
                if message.from_user and message.from_user.username
                else (
                    message.from_user.first_name
                    if message.from_user
                    else "Игрок"
                )
            )
            send_chat_message(
                payload["chat_id"],
                f"⭐ {who} поддержал(а) сервер. Спасибо!",
            )
        except Exception:
            pass
    elif res.get("reason") == "already_credited":
        await message.answer(
            "✅ Этот платёж уже был зачислен ранее. Если что-то не так — "
            "напиши админу."
        )
