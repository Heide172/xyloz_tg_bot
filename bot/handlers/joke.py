from aiogram import Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.joke_service import get_joke_of_day
from services.phrase_service import get_phrase_of_day

router = Router()
logger = get_logger(__name__)


@router.message(Command("joke"))
async def cmd_joke(msg: types.Message):
    text = (msg.text or "")
    force = "--new" in text and msg.from_user and is_admin_tg_id(msg.from_user.id)
    progress = await msg.answer("Думаю над анекдотом…")
    try:
        joke = await get_joke_of_day(force=force)
    except Exception as exc:
        logger.exception("joke generation failed")
        await progress.edit_text(f"Не получилось: {exc}")
        return
    await progress.edit_text(joke)


@router.message(Command("phrase"))
async def cmd_phrase(msg: types.Message):
    text = (msg.text or "")
    force = "--new" in text and msg.from_user and is_admin_tg_id(msg.from_user.id)
    progress = await msg.answer("Слушаю чат, формулирую…")
    try:
        phrase = await get_phrase_of_day(chat_id=msg.chat.id, force=force)
    except Exception as exc:
        logger.exception("phrase generation failed for chat %s", msg.chat.id)
        await progress.edit_text(f"Не получилось: {exc}")
        return
    await progress.edit_text(f"Фраза дня:\n\n{phrase}")
