import asyncio
from queue import Empty, Queue

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.daily_pick_service import pick_participant_of_day
from services.economy_service import get_balance
from services.message_service import save_message
from services.nominations_service import NOMINATION_FAG, award_fag
from services.summary_service import (
    build_summary_prompt,
    get_available_models,
    get_summary_model,
    get_summary_instruction,
    parse_summary_count,
    reset_summary_instruction,
    set_summary_model,
    set_summary_instruction,
    stream_summary,
)

router = Router()
logger = get_logger(__name__)


def _format_stream_text(limit: int, text: str, done: bool) -> str:
    body = text.strip() if text.strip() else "Генерирую..."
    return f"Краткий пересказ последних {limit} сообщений:\n\n{body}"


def _format_reasoning_preview(reasoning: str, tail_limit: int = 400) -> str:
    tail = reasoning.replace("\n", " ").strip()
    if len(tail) > tail_limit:
        tail = "…" + tail[-tail_limit:]
    return f"Думаю над пересказом…\n\n{tail}"


async def _safe_edit_text(message: types.Message, text: str):
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


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


def _is_draft_unsupported(exc: TelegramBadRequest) -> bool:
    return "TEXTDRAFT" in str(exc).upper()


async def _run_streaming_summary(msg: types.Message, limit: int, custom_task: str | None = None):
    chat_id = msg.chat.id
    thread_id = msg.message_thread_id
    draft_id = msg.message_id  # уникальный non-zero per chat

    try:
        prompt = build_summary_prompt(
            chat_id=chat_id,
            limit=limit,
            exclude_message_id=msg.message_id,
            custom_task=custom_task,
        )
    except RuntimeError as exc:
        await msg.answer(str(exc))
        return

    use_drafts = True
    progress: types.Message | None = None
    initial_text = "Собираю контекст..."
    try:
        await msg.bot.send_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            text=initial_text,
            message_thread_id=thread_id,
        )
    except TelegramBadRequest as exc:
        if not _is_draft_unsupported(exc):
            raise
        use_drafts = False
        progress = await msg.answer(initial_text)
        logger.info("drafts unsupported for chat %s (%s), falling back to edit-throttling", chat_id, exc)

    content_q: Queue[str] = Queue()
    reasoning_q: Queue[str] = Queue()
    done = False
    full_text = ""
    reasoning_text = ""
    last_pushed = initial_text

    async def push(text: str):
        nonlocal last_pushed
        if text == last_pushed:
            return
        try:
            if use_drafts:
                await msg.bot.send_message_draft(
                    chat_id=chat_id,
                    draft_id=draft_id,
                    text=text,
                    message_thread_id=thread_id,
                )
            else:
                await _safe_edit_text(progress, text)
            last_pushed = text
        except TelegramRetryAfter as exc:
            logger.warning("summary flood control: sleep %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after)

    interval = 1.0 if use_drafts else 2.5

    async def updater():
        nonlocal full_text, reasoning_text
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
                    full_text += content_q.get_nowait()
                    changed = True
                except Empty:
                    break
            if changed:
                if full_text.strip():
                    candidate = _format_stream_text(limit, full_text, done=False)[:4096]
                else:
                    candidate = _format_reasoning_preview(reasoning_text)[:4096]
                try:
                    await push(candidate)
                except TelegramRetryAfter as exc:
                    logger.warning("summary updater flood: sleep %ss", exc.retry_after)
                    await asyncio.sleep(exc.retry_after)
                except Exception:
                    logger.exception("stream update failed")
            await asyncio.sleep(interval)

    async def report_error(text: str):
        if progress is not None:
            await _safe_edit_text(progress, text)
        else:
            await msg.answer(text)

    updater_task = asyncio.create_task(updater())
    try:
        summary_text = await asyncio.to_thread(
            stream_summary,
            prompt,
            content_q.put,
            reasoning_q.put,
        )
        while not content_q.empty():
            full_text += content_q.get_nowait()
        done = True
        await updater_task

        final_text = f"Краткий пересказ последних {limit} сообщений:\n\n{summary_text or full_text}"
        final_chunks = _split_text_chunks(final_text)
        if use_drafts:
            for chunk in final_chunks:
                await msg.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    message_thread_id=thread_id,
                )
        else:
            await _safe_edit_text(progress, final_chunks[0])
            for chunk in final_chunks[1:]:
                await msg.answer(chunk)
    except RuntimeError as exc:
        done = True
        await updater_task
        await report_error(f"Не удалось сделать пересказ: {exc}")
    except Exception:
        done = True
        await updater_task
        logger.error("summary handler internal error", exc_info=True)
        await report_error("Не удалось сделать пересказ из-за внутренней ошибки.")


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

    # Бонус: начисляется один раз в сутки (идемпотентно).
    bonus_line = ""
    try:
        from common.db.db import SessionLocal
        from common.models.user import User
        session = SessionLocal()
        try:
            winner = session.query(User).filter(User.tg_id == result.winner_tg_id).first()
        finally:
            session.close()
        if winner is not None:
            awarded = award_fag(chat_id=msg.chat.id, user_id=winner.id, day_msk=result.day_msk)
            if awarded:
                new_bal = get_balance(winner.id, msg.chat.id, auto_start=True)
                bonus_line = f"\nБонус: +{awarded} коинов (баланс: {new_bal})"
    except Exception:
        logger.exception("fag bonus award failed")

    await msg.answer(
        "Пидор дня: {who}\n"
        "За день: {day}\n"
        "Статус: {status} (сброс после 00:00 МСК){bonus}".format(
            who=who,
            day=result.candidates_day_msk.strftime("%d.%m.%Y"),
            status=status,
            bonus=bonus_line,
        )
    )

@router.message()
async def message_handler(msg: types.Message):
    save_message(msg)
