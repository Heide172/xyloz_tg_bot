import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List

from common.db.db import SessionLocal
from common.db.db import engine
from common.models.bot_setting import BotSetting
from common.models.message import Message
from common.models.user import User
from common import prompts
from services import ai_client


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and v != "":
            return v
    return default


MAX_MESSAGES = max(1, int(_env("AI_MAX_MESSAGES", "OPENROUTER_MAX_MESSAGES", default="1000")))
MAX_INPUT_TOKENS = int(_env("AI_MAX_INPUT_TOKENS", "OPENROUTER_MAX_INPUT_TOKENS", default="12000"))
MAX_CHARS_PER_MESSAGE = int(_env("AI_MAX_CHARS_PER_MESSAGE", "OPENROUTER_MAX_CHARS_PER_MESSAGE", default="800"))
MAX_CUSTOM_PROMPT_CHARS = int(_env("AI_MAX_CUSTOM_PROMPT_CHARS", "OPENROUTER_MAX_CUSTOM_PROMPT_CHARS", default="1200"))
CHARS_PER_TOKEN = 4


@dataclass
class ChatMessage:
    author: str
    text: str


SUMMARY_PROMPT_KEY = "summary_instruction"
SUMMARY_MODEL_KEY = "summary_model"
DEFAULT_SUMMARY_MODEL = os.getenv("YANDEX_MODEL", "yandexgpt/latest")
DEFAULT_AVAILABLE_MODELS = [
    "yandexgpt/latest",
    "gpt-oss-20b",
    "gpt-oss-120b",
    "qwen3-235b",
    "opencode-go/qwen3.5-plus",
    "opencode-go/qwen3.6-plus",
    "opencode-go/deepseek-v4-flash",
    "opencode-go/deepseek-v4-pro",
    "opencode-go/mimo-v2.5-pro",
    "opencode-go/kimi-k2.6",
    "opencode-go/glm-5.1",
]


def get_available_models() -> List[str]:
    raw = (os.getenv("YANDEX_AVAILABLE_MODELS") or "").strip()
    if raw:
        items = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        items = DEFAULT_AVAILABLE_MODELS[:]
    seen = set()
    result: List[str] = []
    for m in items:
        if m in seen:
            continue
        seen.add(m)
        result.append(m)
    return result


def _ensure_settings_table():
    BotSetting.__table__.create(bind=engine, checkfirst=True)


def get_summary_instruction() -> str:
    _ensure_settings_table()
    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == SUMMARY_PROMPT_KEY).first()
        if row and row.value and row.value.strip():
            return row.value.strip()
        return prompts.load("summary_system")
    finally:
        session.close()


def get_summary_model() -> str:
    _ensure_settings_table()
    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == SUMMARY_MODEL_KEY).first()
        if row and row.value and row.value.strip():
            return row.value.strip()
        return DEFAULT_SUMMARY_MODEL
    finally:
        session.close()


def set_summary_model(value: str, updated_by_tg_id: int | None = None):
    _ensure_settings_table()
    clean_value = value.strip()
    if not clean_value:
        raise ValueError("Модель не может быть пустой")

    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == SUMMARY_MODEL_KEY).first()
        if not row:
            row = BotSetting(
                key=SUMMARY_MODEL_KEY,
                value=clean_value,
                updated_by_tg_id=updated_by_tg_id,
            )
            session.add(row)
        else:
            row.value = clean_value
            row.updated_by_tg_id = updated_by_tg_id
            row.updated_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def set_summary_instruction(value: str, updated_by_tg_id: int | None = None):
    _ensure_settings_table()
    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == SUMMARY_PROMPT_KEY).first()
        clean_value = value.strip()
        if not row:
            row = BotSetting(
                key=SUMMARY_PROMPT_KEY,
                value=clean_value,
                updated_by_tg_id=updated_by_tg_id,
            )
            session.add(row)
        else:
            row.value = clean_value
            row.updated_by_tg_id = updated_by_tg_id
            row.updated_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_summary_instruction(updated_by_tg_id: int | None = None):
    set_summary_instruction(prompts.load("summary_system"), updated_by_tg_id=updated_by_tg_id)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _fit_messages_to_token_budget(messages: List[ChatMessage], max_input_tokens: int) -> tuple[List[ChatMessage], int]:
    selected: List[ChatMessage] = []
    used = 0

    for item in reversed(messages):
        clipped = ChatMessage(
            author=item.author,
            text=_truncate_text(item.text, MAX_CHARS_PER_MESSAGE),
        )
        line = f"- {clipped.author}: {clipped.text}"
        line_tokens = _estimate_tokens(line)
        if selected and used + line_tokens > max_input_tokens:
            break
        if not selected and line_tokens > max_input_tokens:
            selected.append(
                ChatMessage(
                    author=clipped.author,
                    text=_truncate_text(clipped.text, max(80, MAX_CHARS_PER_MESSAGE // 4)),
                )
            )
            break
        selected.append(clipped)
        used += line_tokens

    selected.reverse()
    omitted = max(0, len(messages) - len(selected))
    return selected, omitted


def parse_summary_count(command_text: str, default: int = 20) -> int:
    parts = (command_text or "").split()
    if len(parts) < 2:
        return default

    try:
        value = int(parts[1])
    except ValueError:
        raise ValueError("N должно быть целым числом, например: /summary 30")

    if value < 1 or value > MAX_MESSAGES:
        raise ValueError(f"N должно быть в диапазоне 1..{MAX_MESSAGES}")
    return value


def get_recent_text_messages(chat_id: int, limit: int, exclude_message_id: int | None = None) -> List[ChatMessage]:
    session = SessionLocal()
    try:
        query = (
            session.query(Message, User)
            .outerjoin(User, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.text.isnot(None),
                Message.text != "",
            )
            .order_by(Message.created_at.desc())
        )

        if exclude_message_id is not None:
            query = query.filter(Message.telegram_message_id != exclude_message_id)

        rows = query.limit(limit).all()

        messages: List[ChatMessage] = []
        for msg, user in rows:
            if user and user.username:
                author = f"@{user.username}"
            elif user and user.fullname:
                author = user.fullname
            else:
                author = "Unknown"
            messages.append(ChatMessage(author=author, text=msg.text.strip()))

        return list(reversed(messages))
    finally:
        session.close()


def _build_prompt(messages: List[ChatMessage], custom_task: str | None = None) -> str:
    selected, omitted = _fit_messages_to_token_budget(messages, MAX_INPUT_TOKENS)
    lines = [prompts.load("summary_task"), ""]
    if custom_task:
        lines.extend(
            [
                "Дополнительный фокус от пользователя:",
                _truncate_text(custom_task.strip(), MAX_CUSTOM_PROMPT_CHARS),
                "Если это противоречит данным чата, приоритет у фактов из сообщений.",
                "",
            ]
        )

    lines.append("Сообщения:")
    if omitted:
        lines.append(f"(Пропущено старых сообщений из-за лимита контекста: {omitted})")
    for item in selected:
        lines.append(f"- {item.author}: {item.text}")
    return "\n".join(lines)


def stream_yandex_completion(prompt: str, on_delta) -> str:
    return ai_client.stream(
        prompt,
        model=get_summary_model(),
        on_delta=on_delta,
        system_prompt=get_summary_instruction(),
    )


async def summarize_recent_messages(
    chat_id: int,
    limit: int,
    exclude_message_id: int | None = None,
    custom_task: str | None = None,
) -> str:
    messages = get_recent_text_messages(chat_id=chat_id, limit=limit, exclude_message_id=exclude_message_id)
    if not messages:
        return "Недостаточно данных: в чате нет текстовых сообщений для пересказа."

    prompt = _build_prompt(messages, custom_task=custom_task)
    summary = await asyncio.to_thread(
        ai_client.call,
        prompt,
        get_summary_model(),
        get_summary_instruction(),
    )
    return summary


def build_summary_prompt(
    chat_id: int,
    limit: int,
    exclude_message_id: int | None = None,
    custom_task: str | None = None,
) -> str:
    messages = get_recent_text_messages(chat_id=chat_id, limit=limit, exclude_message_id=exclude_message_id)
    if not messages:
        raise RuntimeError("Недостаточно данных: в чате нет текстовых сообщений для пересказа.")
    return _build_prompt(messages, custom_task=custom_task)
