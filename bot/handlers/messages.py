import asyncio
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.daily_pick_service import pick_participant_of_day
from services.message_service import save_message
from services.summary_service import (
    build_summary_prompt,
    get_available_models,
    get_summary_model,
    get_summary_instruction,
    parse_summary_count,
    reset_summary_instruction,
    set_summary_model,
    set_summary_instruction,
    stream_openrouter_summary_sync,
)

router = Router()
logger = get_logger(__name__)


def _format_stream_text(limit: int, text: str, done: bool) -> str:
    body = text.strip() if text.strip() else "Генерирую..."
    postfix = "" if done else "\n\n⏳ Генерирую..."
    result = f"Краткий пересказ последних {limit} сообщений:\n\n{body}{postfix}"
    return result[:3900]


def _split_text_chunks(text: str, chunk_size: int = 3900) -> list[str]:
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


async def _safe_edit_text(message: types.Message, text: str):
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return
        raise


def _parse_custom_summary_args(command_text: str) -> tuple[int, str]:
    parts = (command_text or "").split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Формат: /summary_custom N | ваш промпт")

    tail = parts[1].strip()
    if "|" in tail:
        left, prompt = tail.split("|", 1)
        left = left.strip()
        prompt = prompt.strip()
    else:
        tokens = tail.split(maxsplit=1)
        if tokens and tokens[0].isdigit():
            left = tokens[0]
            prompt = tokens[1].strip() if len(tokens) > 1 else ""
        else:
            left = ""
            prompt = tail

    if not prompt:
        raise ValueError("Формат: /summary_custom N | ваш промпт")

    limit = parse_summary_count(f"/summary {left}") if left else parse_summary_count("/summary 20")
    return limit, prompt


async def _run_streaming_summary(msg: types.Message, limit: int, custom_task: str | None = None):
    progress = await msg.answer("Собираю контекст...")
    try:
        prompt = build_summary_prompt(
            chat_id=msg.chat.id,
            limit=limit,
            exclude_message_id=msg.message_id,
            custom_task=custom_task,
        )
    except RuntimeError as exc:
        await _safe_edit_text(progress, str(exc))
        return

    await _safe_edit_text(progress, "Запускаю генерацию...")
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
                    await _safe_edit_text(progress, candidate)
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

        final_text = f"Краткий пересказ последних {limit} сообщений:\n\n{summary_text or full_text}"
        final_chunks = _split_text_chunks(final_text)
        if final_chunks[0] != last_sent:
            await _safe_edit_text(progress, final_chunks[0])
        for extra in final_chunks[1:]:
            await msg.answer(extra)
    except RuntimeError as exc:
        done = True
        await updater_task
        await _safe_edit_text(progress, f"Не удалось сделать пересказ: {exc}")
    except Exception:
        done = True
        await updater_task
        logger.error("summary handler internal error", exc_info=True)
        await _safe_edit_text(progress, "Не удалось сделать пересказ из-за внутренней ошибки.")


def _require_admin(msg: types.Message) -> bool:
    if not msg.from_user:
        return False
    return is_admin_tg_id(msg.from_user.id)


@router.message(Command("prompt_show"))
async def prompt_show_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    prompt = get_summary_instruction()
    await msg.answer(f"Текущий prompt для пересказа:\n\n{prompt}")


@router.message(Command("prompt_set"))
async def prompt_set_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Формат: /prompt_set ваш новый prompt")
        return
    set_summary_instruction(parts[1], updated_by_tg_id=msg.from_user.id if msg.from_user else None)
    await msg.answer("Prompt обновлен.")


@router.message(Command("prompt_reset"))
async def prompt_reset_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    reset_summary_instruction(updated_by_tg_id=msg.from_user.id if msg.from_user else None)
    await msg.answer("Prompt сброшен на значение по умолчанию.")


@router.message(Command("model_show"))
async def model_show_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    await msg.answer(f"Текущая модель пересказа: {get_summary_model()}")


@router.message(Command("model_list"))
async def model_list_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    current = get_summary_model()
    models = get_available_models()
    lines = ["Доступные модели:"]
    for model in models:
        mark = " (текущая)" if model == current else ""
        lines.append(f"- {model}{mark}")
    await msg.answer("\n".join(lines))


@router.message(Command("model_set"))
async def model_set_handler(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Команда доступна только администраторам бота.")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Формат: /model_set <модель>, например /model_set yandexgpt/latest")
        return
    try:
        set_summary_model(parts[1], updated_by_tg_id=msg.from_user.id if msg.from_user else None)
    except ValueError as exc:
        await msg.answer(str(exc))
        return
    await msg.answer("Модель пересказа обновлена.")


@router.message(Command("summary"))
@router.message(Command("sum"))
async def summary_handler(msg: types.Message):
    try:
        limit = parse_summary_count(msg.text or "")
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    await _run_streaming_summary(msg, limit)


@router.message(Command("summary_custom"))
@router.message(Command("sumc"))
async def summary_custom_handler(msg: types.Message):
    try:
        limit, custom_prompt = _parse_custom_summary_args(msg.text or "")
    except ValueError as exc:
        await msg.answer(str(exc))
        return

    await _run_streaming_summary(msg, limit, custom_task=custom_prompt)


@router.message(Command("fag"))
async def participant_of_day_handler(msg: types.Message):
    """
    Picks a random participant among those who wrote at least once yesterday (MSK).
    Result is fixed for the current MSK day.
    """
    try:
        picked_by = msg.from_user.id if msg.from_user else None
        result = pick_participant_of_day(chat_id=msg.chat.id, picked_by_tg_id=picked_by)
    except RuntimeError as exc:
        await msg.answer(str(exc))
        return
    except Exception:
        logger.error("participant_of_day internal error", exc_info=True)
        await msg.answer("Не удалось выбрать пидора дня из-за внутренней ошибки.")
        return

    if result.winner_username:
        who = f"@{result.winner_username}"
    elif result.winner_fullname:
        who = result.winner_fullname
    else:
        who = str(result.winner_tg_id)

    status = "выбран" if result.is_new else "уже выбран"
    await msg.answer(
        "Пидор дня: {who}\n"
        "За день: {day}\n"
        "Статус: {status} (сброс после 00:00 МСК)".format(
            who=who,
            day=result.candidates_day_msk.strftime("%d.%m.%Y"),
            status=status,
        )
    )

@router.message()
async def message_handler(msg: types.Message):
    save_message(msg)
