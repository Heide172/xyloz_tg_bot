from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.topics_service import (
    TOPICS_DEFAULT_DAYS,
    discover_topics,
    parse_topics_days,
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


@router.message(Command("topics"))
async def cmd_topics(msg: types.Message):
    try:
        days = parse_topics_days(msg.text or "/topics", default=TOPICS_DEFAULT_DAYS)
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    progress = await msg.answer(f"Считаю темы за {days} дн. (эмбеддинги + кластеризация)…")
    try:
        topics = await discover_topics(chat_id=msg.chat.id, days=days)
    except Exception as exc:
        logger.exception("topics failed for chat %s", msg.chat.id)
        await _safe_edit(progress, f"Не удалось посчитать темы: {exc}")
        return

    if topics is None:
        await _safe_edit(
            progress,
            f"Мало данных за {days} дн.: нужно минимум 30 сообщений длиной от 20 символов.",
        )
        return
    if not topics:
        await _safe_edit(progress, f"За {days} дн. кластеризация не нашла осмысленных тем.")
        return

    lines = [f"Темы чата за {days} дн.", ""]
    for i, t in enumerate(topics, 1):
        lines.append(f"{i}. {t['label']} ({t['size']} сообщ.)")
        if t["authors"]:
            lines.append(f"   Авторы: {' '.join(t['authors'])}")
        for ex in t["examples"]:
            ex_clip = ex[:140].replace("\n", " ")
            lines.append(f"   • {ex_clip}")
        lines.append("")

    result = "\n".join(lines).rstrip()
    chunks = _split_chunks(result)
    await _safe_edit(progress, chunks[0])
    for extra in chunks[1:]:
        await msg.answer(extra)
