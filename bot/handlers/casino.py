"""Команда /casino — открывает Telegram Mini App."""
import os

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from common.logger.logger import get_logger

logger = get_logger(__name__)
router = Router()

MINIAPP_URL = (os.getenv("MINIAPP_URL") or "").strip()


@router.message(Command("casino"))
async def cmd_casino(msg: types.Message):
    if not MINIAPP_URL:
        await msg.answer(
            "Mini App не настроен (env MINIAPP_URL пуст). "
            "Используй текстовые команды: /balance /markets /portfolio /leaderboard."
        )
        return

    # chat_id передаётся в URL, на backend проверим membership.
    url = MINIAPP_URL
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}chat_id={msg.chat.id}"

    button = InlineKeyboardButton(text="Открыть казино", web_app=WebAppInfo(url=url))
    markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
    await msg.answer(
        "Казино чата: ставки, баланс, лидерборд.",
        reply_markup=markup,
    )
