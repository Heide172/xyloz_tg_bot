from aiogram import Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.mood_service import (
    DEFAULT_DAYS,
    build_mood_report,
    build_toxic_report,
    parse_days,
)

router = Router()
logger = get_logger(__name__)


@router.message(Command("mood"))
async def cmd_mood(msg: types.Message):
    try:
        days = parse_days(msg.text or "/mood", default=DEFAULT_DAYS)
    except ValueError as exc:
        await msg.answer(str(exc))
        return
    try:
        text = build_mood_report(chat_id=msg.chat.id, days=days)
    except Exception as exc:
        logger.exception("mood report failed in chat %s", msg.chat.id)
        await msg.answer(f"Не удалось собрать отчёт: {exc}")
        return
    await msg.answer(text)


@router.message(Command("toxic"))
async def cmd_toxic(msg: types.Message):
    try:
        days = parse_days(msg.text or "/toxic", default=DEFAULT_DAYS)
    except ValueError as exc:
        await msg.answer(str(exc))
        return
    try:
        text = build_toxic_report(chat_id=msg.chat.id, days=days)
    except Exception as exc:
        logger.exception("toxic report failed in chat %s", msg.chat.id)
        await msg.answer(f"Не удалось собрать отчёт: {exc}")
        return
    await msg.answer(text)
