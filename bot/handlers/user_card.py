import asyncio
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.user_card_service import (
    resolve_user_for_card,
    stream_user_card,
)

router = Router()
logger = get_logger(__name__)

MAX_TG_TEXT = 3900
UPDATE_INTERVAL_SEC = 3.0
REASONING_TAIL_CHARS = 400


def _split_chunks(text: str, chunk_size: int = MAX_TG_TEXT) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind("\n", i, end)
            if split_at > i + 200:
                end = split_at + 1
        chunks.append(text[i:end].rstrip())
        i = end
    return chunks


async def _safe_edit(message: types.Message, text: str):
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


def _format_reasoning_preview(reasoning: str) -> str:
    tail = reasoning.replace("\n", " ").strip()
    if len(tail) > REASONING_TAIL_CHARS:
        tail = "…" + tail[-REASONING_TAIL_CHARS:]
    return f"Собираю карточку…\n\n{tail}"


def _format_content_preview(content: str) -> str:
    return f"Карточка участника (генерирую…)\n\n{content.strip()}"[:MAX_TG_TEXT + 100]


@router.message(Command("card"))
async def cmd_card(msg: types.Message):
    reply_tg_id = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        reply_tg_id = msg.reply_to_message.from_user.id

    fallback_tg_id = msg.from_user.id if msg.from_user else None
    arg_text = (msg.text or "").split(maxsplit=1)
    arg = arg_text[1] if len(arg_text) > 1 else None

    user = resolve_user_for_card(
        chat_id=msg.chat.id,
        arg_text=arg,
        fallback_tg_id=fallback_tg_id,
        reply_to_tg_id=reply_tg_id,
    )
    if user is None:
        await msg.answer(
            "Не нашёл участника. Используй: /card @username, либо ответь /card на сообщение, либо просто /card для своей карточки."
        )
        return

    progress = await msg.answer(f"Собираю карточку для @{user.username or user.fullname or user.tg_id}...")

    content_q: Queue[str] = Queue()
    reasoning_q: Queue[str] = Queue()
    done = False
    content_text = ""
    reasoning_text = ""
    last_pushed = ""

    async def push(text: str):
        nonlocal last_pushed
        if text == last_pushed:
            return
        try:
            await _safe_edit(progress, text)
            last_pushed = text
        except TelegramRetryAfter as exc:
            logger.warning("card flood control: sleep %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except Exception:
            logger.exception("card progress update failed")

    async def updater():
        nonlocal content_text, reasoning_text
        while not done or not content_q.empty() or not reasoning_q.empty():
            changed = False
            while True:
                try:
                    reasoning_text += reasoning_q.get_nowait()
                    changed = True
                except Empty:
                    break
            while True:
                try:
                    content_text += content_q.get_nowait()
                    changed = True
                except Empty:
                    break
            if changed:
                if content_text.strip():
                    candidate = _format_content_preview(content_text)
                else:
                    candidate = _format_reasoning_preview(reasoning_text)
                await push(candidate)
            await asyncio.sleep(UPDATE_INTERVAL_SEC)

    updater_task = asyncio.create_task(updater())
    try:
        header, llm_text = await stream_user_card(
            chat_id=msg.chat.id,
            user=user,
            on_delta=content_q.put,
            on_reasoning=reasoning_q.put,
        )
        while not content_q.empty():
            content_text += content_q.get_nowait()
        done = True
        await updater_task

        if not llm_text:
            await _safe_edit(progress, header)
            return

        final = f"{header}\n\n{llm_text}"
        chunks = _split_chunks(final)
        await _safe_edit(progress, chunks[0])
        for extra in chunks[1:]:
            await msg.answer(extra)
    except Exception as exc:
        done = True
        await updater_task
        logger.exception("user card failed in chat %s for user %s", msg.chat.id, user.id)
        await _safe_edit(progress, f"Не удалось собрать карточку: {exc}")
