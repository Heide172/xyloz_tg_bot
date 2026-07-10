"""Двойник дня — outer middleware на текстовые сообщения чата.

Реализовано как middleware, а НЕ handler, потому что:
  - в aiogram 3 первый matched handler consume'ит апдейт;
  - twin не должен мешать основному message_router (логирование, NLP);
  - twin-ответ — fire-and-forget (через asyncio.create_task), middleware
    мгновенно отдаёт управление дальше.
"""
import asyncio
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from common.logger.logger import get_logger
from services.duel_mute_registry import is_bot_muted
from services.message_service import random_recent_sticker
from services.twin_reply import (
    ENABLED as TWIN_ENABLED,
    craft_reply_sync,
    note_message,
    post_reply,
    should_reply,
)
from services.twin_service import get_state

logger = get_logger(__name__)

_MENTION_RE = re.compile(r"(?:^|\s)@([A-Za-z][A-Za-z0-9_]{4,31})")


def _extract_mentions(text: str) -> list[str]:
    return [m.group(1) for m in _MENTION_RE.finditer(text or "")]


def _author_label(msg: Message) -> str:
    u = msg.from_user
    if not u:
        return "?"
    return u.username or u.full_name or f"id{u.id}"


async def _maybe_reply(message: Message) -> None:
    logger.debug("twin_mw: hit msg_id=%s chat=%s text=%r",
                 message.message_id, message.chat.id if message.chat else None,
                 (message.text or "")[:50])
    if not TWIN_ENABLED:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if not message.chat or message.chat.type not in ("group", "supergroup"):
        return
    if not message.text:
        return
    if message.text.startswith("/"):
        return
    chat_id = message.chat.id
    note_message(chat_id)

    state = get_state(chat_id)
    if not state or not state.get("target_user_id"):
        logger.debug("twin_mw: no state/target for chat=%s", chat_id)
        return
    # target пишет сам — двойник молчит
    if message.from_user and message.from_user.id == state.get("target_tg_id"):
        return

    mentions = _extract_mentions(message.text)
    target_uname = (state.get("target_name") or "").lstrip("@").lower()
    bot_uname = ""
    if message.bot:
        try:
            bot_uname = ((await message.bot.me()).username or "").lower()
        except Exception:
            bot_uname = ""

    # Тег нашего бота в тексте — тоже триггер «обращаются к двойнику».
    mention_lc = [m.lower() for m in mentions]
    if bot_uname and bot_uname in mention_lc:
        mention_lc.append(target_uname)  # форсим match в should_reply

    is_reply_to_target = False
    # reply на сообщение настоящего target-юзера ИЛИ на ответ самого бота
    # (продолжение диалога с двойником — должен подхватывать).
    if message.reply_to_message and message.reply_to_message.from_user:
        rt_user = message.reply_to_message.from_user
        rt_uname = (rt_user.username or "").lower()
        if target_uname and rt_uname == target_uname:
            is_reply_to_target = True
        elif message.bot and rt_user.id == (await message.bot.me()).id:
            is_reply_to_target = True

    decision = should_reply(
        state, message.text, mention_lc, is_reply_to_target, None
    )
    logger.info(
        "twin_mw: chat=%s target=@%s mentions=%s reply_to_target=%s → reply=%s",
        chat_id, target_uname, mentions, is_reply_to_target, decision,
    )
    if not decision:
        return

    # Бот проиграл кому-то в /duelbot → он сам в муте: вместо болтовни отвечает
    # рандомным недавним стикером чата (нет стикеров — молчит).
    if is_bot_muted(chat_id):
        file_id = await asyncio.to_thread(random_recent_sticker, chat_id)
        if file_id:
            try:
                await message.bot.send_sticker(
                    chat_id, file_id, reply_to_message_id=message.message_id
                )
            except Exception:
                logger.exception("twin sticker-mute send failed chat=%s", chat_id)
        return

    try:
        text = await asyncio.to_thread(
            craft_reply_sync,
            state,
            message.text,
            _author_label(message),
            message.message_id,
        )
        if not text:
            return
        await post_reply(message.bot, state, message.message_id, text)
    except Exception:
        logger.exception("twin reply pipeline failed chat=%s", chat_id)


class TwinMiddleware(BaseMiddleware):
    """Outer middleware на message-апдейты. Запускает twin-ответ как
    background-таску и сразу пропускает управление основному handler-chain.
    """

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            asyncio.create_task(_maybe_reply(event))
        return await handler(event, data)
