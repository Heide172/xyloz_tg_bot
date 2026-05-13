from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.digest_service import (
    DIGEST_DEFAULT_DAYS,
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


@router.message(Command("digest"))
async def cmd_digest(msg: types.Message):
    try:
        days = parse_digest_days(msg.text or "/digest", default=DIGEST_DEFAULT_DAYS)
    except ValueError as exc:
        await msg.answer(str(exc))
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
