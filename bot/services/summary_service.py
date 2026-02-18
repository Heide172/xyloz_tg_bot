import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
import time
from typing import List
from urllib import error, request

from common.db.db import SessionLocal
from common.db.db import engine
from common.models.bot_setting import BotSetting
from common.models.message import Message
from common.models.user import User


YANDEX_CHAT_COMPLETIONS_URL = os.getenv(
    "YANDEX_CHAT_COMPLETIONS_URL",
    "https://llm.api.cloud.yandex.net/v1/chat/completions",
)
MAX_MESSAGES = max(1, int(os.getenv("OPENROUTER_MAX_MESSAGES", "1000")))
MAX_INPUT_TOKENS = int(os.getenv("OPENROUTER_MAX_INPUT_TOKENS", "12000"))
MAX_CHARS_PER_MESSAGE = int(os.getenv("OPENROUTER_MAX_CHARS_PER_MESSAGE", "800"))
MAX_CUSTOM_PROMPT_CHARS = int(os.getenv("OPENROUTER_MAX_CUSTOM_PROMPT_CHARS", "1200"))
MAX_OUTPUT_TOKENS = int(
    os.getenv("YANDEX_MAX_OUTPUT_TOKENS", os.getenv("OPENROUTER_MAX_OUTPUT_TOKENS", "1200"))
)
YANDEX_MAX_RETRIES = max(1, int(os.getenv("YANDEX_MAX_RETRIES", "2")))
YANDEX_RETRY_DELAY_SEC = float(os.getenv("YANDEX_RETRY_DELAY_SEC", "1.5"))
CHARS_PER_TOKEN = 4


@dataclass
class ChatMessage:
    author: str
    text: str


SUMMARY_INSTRUCTION = (
    "Сделай краткий пересказ чата на русском. "
    "Главное требование: не выдумывай факты, имена и события. "
    "Используй только информацию из входных сообщений."
)
SUMMARY_PROMPT_KEY = "summary_instruction"
SUMMARY_MODEL_KEY = "summary_model"
DEFAULT_SUMMARY_MODEL = os.getenv("YANDEX_MODEL", "yandexgpt/latest")
DEFAULT_AVAILABLE_MODELS = [
    "yandexgpt/latest",
    "gpt-oss-20b",
    "gpt-oss-120b",
    "qwen3-235b",
]


def _messages_for_model(prompt: str) -> list[dict]:
    # Some free providers reject system/developer messages.
    return [
        {
            "role": "user",
            "content": f"{get_summary_instruction()}\n\n{prompt}",
        }
    ]


def _extract_text_payload(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_message_content_from_body(body: dict) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message", {}) if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    content = _extract_text_payload(message.get("content"))
    return content


def _get_yandex_api_key() -> str:
    value = (os.getenv("YANDEX_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("YANDEX_API_KEY не задан")
    return value


def _get_yandex_folder_id() -> str:
    value = (os.getenv("YANDEX_FOLDER_ID") or "").strip()
    if not value:
        raise RuntimeError("YANDEX_FOLDER_ID не задан")
    return value


def _resolve_model_uri(model_value: str, folder_id: str) -> str:
    m = model_value.strip()
    if m.startswith("gpt://"):
        return m
    return f"gpt://{folder_id}/{m}"


def get_available_models() -> List[str]:
    raw = (os.getenv("YANDEX_AVAILABLE_MODELS") or "").strip()
    if raw:
        items = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        items = DEFAULT_AVAILABLE_MODELS[:]
    # Deduplicate preserving order.
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
        return SUMMARY_INSTRUCTION
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
    set_summary_instruction(SUMMARY_INSTRUCTION, updated_by_tg_id=updated_by_tg_id)


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


def _call_openrouter_sync(prompt: str) -> str:
    api_key = _get_yandex_api_key()
    folder_id = _get_yandex_folder_id()
    model_uri = _resolve_model_uri(get_summary_model(), folder_id)

    payload = {
        "model": model_uri,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": _messages_for_model(prompt),
    }

    last_error = ""
    for attempt in range(YANDEX_MAX_RETRIES):
        req = request.Request(
            YANDEX_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "OpenAI-Project": folder_id,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = _extract_message_content_from_body(body).strip()
            if text:
                return text
            raise RuntimeError("Некорректный ответ Yandex API")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_uri}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < YANDEX_MAX_RETRIES:
                time.sleep(YANDEX_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"Yandex API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"Yandex API недоступен: {exc.reason}")

    raise RuntimeError(f"Yandex API error: {last_error or 'unknown'}")


def stream_openrouter_summary_sync(prompt: str, on_delta) -> str:
    api_key = _get_yandex_api_key()
    folder_id = _get_yandex_folder_id()
    model_uri = _resolve_model_uri(get_summary_model(), folder_id)

    payload = {
        "model": model_uri,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": True,
        "messages": _messages_for_model(prompt),
    }

    last_error = ""
    for attempt in range(YANDEX_MAX_RETRIES):
        req = request.Request(
            YANDEX_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "OpenAI-Project": folder_id,
            },
            method="POST",
        )

        full_text = []
        saw_done = False
        hard_error = False
        try:
            with request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[5:].strip()
                    if payload_line == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict) and chunk.get("error"):
                        last_error = f"{model_uri}: {chunk.get('error')}"
                        hard_error = True
                        break

                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first_choice = choices[0] if isinstance(choices[0], dict) else {}
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason:
                        saw_done = True
                    delta = first_choice.get("delta", {}) if isinstance(first_choice.get("delta", {}), dict) else {}
                    content_delta = _extract_text_payload(delta.get("content"))
                    if content_delta:
                        full_text.append(content_delta)
                        on_delta(content_delta)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_uri}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < YANDEX_MAX_RETRIES:
                time.sleep(YANDEX_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"Yandex API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"Yandex API недоступен: {exc.reason}")

        text = "".join(full_text).strip()
        if text and not hard_error:
            if saw_done:
                return text
            # Some providers may cut stream before terminal chunk; try non-stream completion
            # to fetch finalized output instead of returning truncated text.
            try:
                completed = _call_openrouter_sync(prompt).strip()
                if completed:
                    return completed
            except Exception:
                pass
            return text
        last_error = last_error or (
            f"{model_uri}: stream ended without final content "
            "(possibly reasoning-only response)"
        )
        if hard_error:
            break

    raise RuntimeError(f"Yandex API error: {last_error or 'unknown'}")


def _build_prompt(messages: List[ChatMessage], custom_task: str | None = None) -> str:
    selected, omitted = _fit_messages_to_token_budget(messages, MAX_INPUT_TOKENS)
    lines = [
        "Сделай краткий пересказ последних сообщений чата.",
        "Формат: простой список по темам (4-8 пунктов).",
        "Пиши кратко и по существу.",
        "Не добавляй ссылки на сообщения.",
        "Ответ должен быть завершенным: не обрывайся на полуслове или незакрытом пункте.",
        "",
    ]
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
    summary = await asyncio.to_thread(_call_openrouter_sync, prompt)
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
