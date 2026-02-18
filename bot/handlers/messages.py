import asyncio
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.filters import Command
from services.message_service import save_message
from services.summary_service import (
    build_summary_prompt,
    parse_summary_count,
    stream_openrouter_summary_sync,
)

router = Router()


def _format_stream_text(limit: int, text: str, done: bool) -> str:
    body = text.strip() if text.strip() else "Генерирую..."
    postfix = "" if done else "\n\n⏳ Генерирую..."
    result = f"Краткий пересказ последних {limit} сообщений:\n\n{body}{postfix}"
    return result[:3900]


async def _run_streaming_summary(msg: types.Message, limit: int):
    progress = await msg.answer("Собираю контекст...")
    try:
        prompt = build_summary_prompt(
            chat_id=msg.chat.id,
            limit=limit,
            exclude_message_id=msg.message_id,
        )
    except RuntimeError as exc:
        await progress.edit_text(str(exc))
        return

    await progress.edit_text("Запускаю генерацию...")
    chunks: Queue[str] = Queue()
    done = False
    full_text = ""
    last_sent = ""

    async def updater():
        nonlocal full_text, done, last_sent
        while not done or not chunks.empty():
            changed = False
            while True:
                try:
                    full_text += chunks.get_nowait()
                    changed = True
                except Empty:
                    break

            if changed:
                candidate = _format_stream_text(limit, full_text, done=False)
                if candidate != last_sent:
                    await progress.edit_text(candidate)
                    last_sent = candidate
            await asyncio.sleep(1.2)

    updater_task = asyncio.create_task(updater())
    try:
        summary_text = await asyncio.to_thread(
            stream_openrouter_summary_sync,
            prompt,
            chunks.put,
        )
        while not chunks.empty():
            full_text += chunks.get_nowait()
        done = True
        await updater_task

        final = _format_stream_text(limit, summary_text or full_text, done=True)
        if final != last_sent:
            await progress.edit_text(final)
    except RuntimeError as exc:
        done = True
        await updater_task
        await progress.edit_text(f"Не удалось сделать пересказ: {exc}")
    except Exception:
        done = True
        await updater_task
        await progress.edit_text("Не удалось сделать пересказ из-за внутренней ошибки.")


@router.message(Command("summary"))
@router.message(Command("sum"))
async def summary_handler(msg: types.Message):
    try:
        limit = parse_summary_count(msg.text or "")
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    await _run_streaming_summary(msg, limit)

@router.message()
async def message_handler(msg: types.Message):
    save_message(msg)
