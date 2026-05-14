"""Команда /casino — открывает Telegram Mini App через deep-link.

В групповых чатах WebAppInfo на inline-кнопке не работает (BUTTON_TYPE_INVALID).
Используем deep-link `t.me/<bot>?startapp=<chat_id>` — Telegram распознаёт его
и открывает Main Mini App, передавая chat_id в initData.start_param.
"""
import os

from aiogram import Bot, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from common.logger.logger import get_logger

logger = get_logger(__name__)
router = Router()

# Можно переопределить полным URL (например через env), но обычно достаточно бот-username.
DEEPLINK_OVERRIDE = (os.getenv("MINIAPP_DEEPLINK") or "").strip()


async def _build_deeplink(bot: Bot, chat_id: int) -> str | None:
    if DEEPLINK_OVERRIDE:
        sep = "&" if "?" in DEEPLINK_OVERRIDE else "?"
        return f"{DEEPLINK_OVERRIDE}{sep}startapp={chat_id}"
    me = await bot.get_me()
    if not me.username:
        return None
    return f"https://t.me/{me.username}?startapp={chat_id}"


@router.message(Command("casino"))
async def cmd_casino(msg: types.Message):
    link = await _build_deeplink(msg.bot, msg.chat.id)
    if not link:
        await msg.answer("Mini App не настроен.")
        return

    button = InlineKeyboardButton(text="Открыть казино", url=link)
    markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
    await msg.answer(
        "Казино чата: ставки, баланс, лидерборд.",
        reply_markup=markup,
    )
