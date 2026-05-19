"""Ручной вайп фермы (админ). Деструктивно — требует CONFIRM.

Сносит cp/воркеров/уровни, гача-коллекцию, AMM-пул и историю цен.
Роутер подключать ДО message_router.
"""
import asyncio

from aiogram import Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.clicker_service import wipe_farm_sync

router = Router()
logger = get_logger(__name__)

HELP = (
    "Вайп фермы (ДЕСТРУКТИВНО, без отмены):\n"
    "  /farmwipe here CONFIRM   — текущий чат\n"
    "  /farmwipe <chat_id> CONFIRM\n"
    "  /farmwipe all CONFIRM    — ВСЕ чаты\n\n"
    "Сносит: cp, уровни, воркеров, гача-коллекцию, AMM-пул, историю цен. "
    "Пул пересоздастся с якоря."
)


@router.message(Command("farmwipe"))
async def cmd_farmwipe(msg: types.Message):
    if not (msg.from_user and is_admin_tg_id(msg.from_user.id)):
        await msg.answer("Только для админов бота.")
        return

    parts = (msg.text or "").split()
    if len(parts) < 3 or parts[2] != "CONFIRM":
        await msg.answer(HELP)
        return

    target = parts[1].lower()
    if target == "all":
        chat_id = None
    elif target == "here":
        chat_id = msg.chat.id
    else:
        try:
            chat_id = int(target)
        except ValueError:
            await msg.answer("chat_id должен быть числом, 'here' или 'all'.")
            return

    try:
        res = await asyncio.to_thread(wipe_farm_sync, chat_id)
    except Exception:
        logger.exception("farmwipe failed")
        await msg.answer("Вайп упал — см. логи.")
        return

    scope = "ВСЕ чаты" if chat_id is None else f"чат {chat_id}"
    d = res["deleted"]
    await msg.answer(
        f"Ферма вайпнута: {scope}\n"
        f"farms={d['clicker_farms']} gacha={d['gacha_collection']} "
        f"pool={d['clicker_market_pool']} price={d['clicker_market_price']}"
    )
