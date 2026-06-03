"""Outer middleware: полностью игнорирует апдейты из служебных чатов
(напр. канал уведомлений xyloz-check) — не пускает их в основные механики бота.

Env: IGNORE_CHATS — csv id чатов (напр. -4531975186).
"""
import os
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

IGNORE_CHATS = {
    int(x) for x in (os.getenv("IGNORE_CHATS") or "").split(",")
    if x.strip().lstrip("-").isdigit()
}


class IgnoreChatsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        if chat is not None and chat.id in IGNORE_CHATS:
            return None  # игнор — handler не вызываем
        return await handler(event, data)
