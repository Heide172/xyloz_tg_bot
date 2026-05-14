import asyncio

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.joke_service import get_joke_of_day
from services.phrase_service import get_phrase_of_day

router = Router()
logger = get_logger(__name__)

TIMEOUT_SEC = 300


async def _tick(progress: types.Message, label: str) -> None:
    """Каждые 15 сек обновляет прогресс-сообщение, пока не отменено."""
    elapsed = 0
    try:
        while True:
            await asyncio.sleep(15)
            elapsed += 15
            try:
                await progress.edit_text(f"{label} ({elapsed} сек)")
            except TelegramBadRequest:
                pass
    except asyncio.CancelledError:
        return


async def _run_with_progress(progress: types.Message, label: str, coro):
    ticker = asyncio.create_task(_tick(progress, label))
    try:
        return await asyncio.wait_for(coro, timeout=TIMEOUT_SEC)
    finally:
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass


@router.message(Command("joke"))
async def cmd_joke(msg: types.Message):
    text = (msg.text or "")
    force = "--new" in text and msg.from_user and is_admin_tg_id(msg.from_user.id)
    progress = await msg.answer("Думаю над анекдотом…")
    try:
        joke = await _run_with_progress(
            progress, "Думаю над анекдотом…", get_joke_of_day(force=force)
        )
    except asyncio.TimeoutError:
        await progress.edit_text(f"Модель не ответила за {TIMEOUT_SEC} сек. Попробуй позже.")
        return
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
        phrase = await _run_with_progress(
            progress,
            "Слушаю чат, формулирую…",
            get_phrase_of_day(chat_id=msg.chat.id, force=force),
        )
    except asyncio.TimeoutError:
        await progress.edit_text(f"Модель не ответила за {TIMEOUT_SEC} сек. Попробуй позже.")
        return
    except Exception as exc:
        logger.exception("phrase generation failed for chat %s", msg.chat.id)
        await progress.edit_text(f"Не получилось: {exc}")
        return
    await progress.edit_text(f"Фраза дня:\n\n{phrase}")
