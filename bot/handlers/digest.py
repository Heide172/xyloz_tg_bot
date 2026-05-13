import asyncio
from datetime import datetime
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from common.logger.logger import get_logger
from services.digest_service import (
    DIGEST_DEFAULT_DAYS,
    build_digest_payload,
    parse_digest_days,
    stream_digest,
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


def _parse_args(text: str | None) -> tuple[int, bool]:
    parts = (text or "").split()
    debug = False
    cleaned: list[str] = []
    for p in parts:
        if p == "--debug":
            debug = True
        else:
            cleaned.append(p)
    fake_text = " ".join(cleaned) if len(cleaned) > 1 else "/digest"
    days = parse_digest_days(fake_text, default=DIGEST_DEFAULT_DAYS)
    return days, debug


def _format_reasoning_preview(reasoning: str) -> str:
    tail = reasoning.replace("\n", " ").strip()
    if len(tail) > REASONING_TAIL_CHARS:
        tail = "…" + tail[-REASONING_TAIL_CHARS:]
    return f"🧠 Анализирую чат…\n\n{tail}"


def _format_content_preview(days: int, content: str) -> str:
    body = content.strip()
    head = f"📰 Дайджест чата за {days} дн. (генерирую…)"
    return f"{head}\n\n{body}"[:MAX_TG_TEXT + 100]


@router.message(Command("digest"))
async def cmd_digest(msg: types.Message):
    try:
        days, debug = _parse_args(msg.text)
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    if debug:
        progress = await msg.answer(f"Собираю debug-промпт за {days} дн...")
        try:
            header, prompt, data = await build_digest_payload(chat_id=msg.chat.id, days=days)
        except Exception as exc:
            logger.exception("digest debug build failed for chat %s", msg.chat.id)
            await _safe_edit(progress, f"Не удалось собрать debug: {exc}")
            return
        if data is None:
            await _safe_edit(progress, header)
            return
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"digest_debug_{ts}.txt"
        file_bytes = prompt.encode("utf-8")
        await _safe_edit(progress, header)
        await msg.bot.send_document(
            chat_id=msg.chat.id,
            document=BufferedInputFile(file_bytes, filename=filename),
            caption=f"debug-промпт ({len(file_bytes)} байт, ~{len(file_bytes)//4} токенов)",
            message_thread_id=msg.message_thread_id,
        )
        return

    progress = await msg.answer(f"Собираю дайджест за {days} дн...")

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
            logger.warning("digest flood control: sleep %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except Exception:
            logger.exception("digest progress update failed")

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
                    candidate = _format_content_preview(days, content_text)
                else:
                    candidate = _format_reasoning_preview(reasoning_text)
                await push(candidate)
            await asyncio.sleep(UPDATE_INTERVAL_SEC)

    updater_task = asyncio.create_task(updater())
    try:
        header, llm_text = await stream_digest(
            chat_id=msg.chat.id,
            days=days,
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
        logger.exception("digest generation failed for chat %s", msg.chat.id)
        await _safe_edit(progress, f"Не удалось собрать дайджест: {exc}")
