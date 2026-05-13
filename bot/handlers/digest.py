from datetime import datetime

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from common.logger.logger import get_logger
from services.digest_service import (
    DIGEST_DEFAULT_DAYS,
    build_digest_payload,
    generate_digest,
    parse_digest_days,
)

router = Router()
logger = get_logger(__name__)

MAX_TG_TEXT = 3900


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
    """Возвращает (days, debug). Поддерживает /digest [N] [--debug] в любом порядке."""
    parts = (text or "").split()
    debug = False
    cleaned: list[str] = []
    for p in parts:
        if p == "--debug":
            debug = True
        else:
            cleaned.append(p)
    # парсим как обычный /digest [N]
    fake_text = " ".join(cleaned) if len(cleaned) > 1 else "/digest"
    days = parse_digest_days(fake_text, default=DIGEST_DEFAULT_DAYS)
    return days, debug


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
    try:
        result = await generate_digest(chat_id=msg.chat.id, days=days)
    except Exception as exc:
        logger.exception("digest generation failed for chat %s", msg.chat.id)
        await _safe_edit(progress, f"Не удалось собрать дайджест: {exc}")
        return

    chunks = _split_chunks(result)
    await _safe_edit(progress, chunks[0])
    for extra in chunks[1:]:
        await msg.answer(extra)
