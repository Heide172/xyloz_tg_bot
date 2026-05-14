import asyncio
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.ask_service import parse_ask_query, stream_ask

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
    return f"Думаю над вопросом…\n\n{tail}"


def _format_content_preview(content: str) -> str:
    return f"Формирую ответ…\n\n{content.strip()}"[:MAX_TG_TEXT + 100]


@router.message(Command("ask"))
async def cmd_ask(msg: types.Message):
    try:
        query = parse_ask_query(msg.text)
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    progress = await msg.answer("Ищу в истории чата…")

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
            logger.warning("ask flood control: sleep %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except Exception:
            logger.exception("ask progress update failed")

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
        header, llm_text, results = await stream_ask(
            chat_id=msg.chat.id,
            query=query,
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
        logger.exception("ask failed for chat %s", msg.chat.id)
        await _safe_edit(progress, f"Не удалось ответить: {exc}")
