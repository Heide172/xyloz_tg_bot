from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.user_card_service import generate_user_card, resolve_user_for_card

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
    try:
        result = await generate_user_card(chat_id=msg.chat.id, user=user)
    except Exception as exc:
        logger.exception("user card failed in chat %s for user %s", msg.chat.id, user.id)
        await _safe_edit(progress, f"Не удалось собрать карточку: {exc}")
        return

    chunks = _split_chunks(result)
    await _safe_edit(progress, chunks[0])
    for extra in chunks[1:]:
        await msg.answer(extra)
