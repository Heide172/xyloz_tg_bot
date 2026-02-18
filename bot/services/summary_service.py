import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List
from urllib import error, request

from common.db.db import SessionLocal
from common.db.db import engine
from common.models.bot_setting import BotSetting
from common.models.message import Message
from common.models.user import User


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = [
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-7b-instruct:free",
]
MAX_MESSAGES = max(1, int(os.getenv("OPENROUTER_MAX_MESSAGES", "1000")))
MAX_INPUT_TOKENS = int(os.getenv("OPENROUTER_MAX_INPUT_TOKENS", "12000"))
MAX_CHARS_PER_MESSAGE = int(os.getenv("OPENROUTER_MAX_CHARS_PER_MESSAGE", "800"))
MAX_CUSTOM_PROMPT_CHARS = int(os.getenv("OPENROUTER_MAX_CUSTOM_PROMPT_CHARS", "1200"))
CHARS_PER_TOKEN = 4


@dataclass
class ChatMessage:
    author: str
    text: str


SUMMARY_INSTRUCTION = (
    "Сделай нейтральный деловой пересказ чата на русском. "
    "Пиши только факты по делу, без оценок и без цитирования оскорблений. "
    "Если есть троллинг/флейм/личные выпады, не пересказывай детали, "
    "а кратко пометь как 'флуд/конфликт'. "
    "Не придумывай факты. Не используй грубую лексику. "
    "Не подменяй личности и имена: используй только имена/ники, встречающиеся во входных данных. "
    "Если факт, имя или связь неочевидны, явно пиши 'не удалось достоверно определить'."
)
SUMMARY_PROMPT_KEY = "summary_instruction"


def _messages_for_model(prompt: str) -> list[dict]:
    # Some free providers reject system/developer messages.
    return [
        {
            "role": "user",
            "content": f"{get_summary_instruction()}\n\n{prompt}",
        }
    ]


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
                ChatMessage(author=clipped.author, text=_truncate_text(clipped.text, max(80, MAX_CHARS_PER_MESSAGE // 4)))
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
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    payload = {
        "temperature": 0.0,
        "max_tokens": 250,
        "messages": _messages_for_model(prompt),
    }

    models = _resolve_models()
    last_error = ""
    for model in models:
        model_payload = dict(payload, model=model)
        req = request.Request(
            OPENROUTER_URL,
            data=json.dumps(model_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://xyloz-tg-bot.local",
                "X-Title": "xyloz_tg_bot",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            try:
                return body["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError):
                raise RuntimeError("Некорректный ответ LLM API")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model}: {exc.code} {details[:200]}"
            if exc.code in (404, 429):
                continue
            raise RuntimeError(f"LLM API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"LLM API недоступен: {exc.reason}")

    raise RuntimeError(
        "Не найдено доступных endpoint'ов для моделей. "
        "Укажи рабочую модель в OPENROUTER_MODEL. "
        f"Последняя ошибка: {last_error or 'n/a'}"
    )


def _resolve_models() -> List[str]:
    models: List[str] = []
    single = (os.getenv("OPENROUTER_MODEL") or "").strip()
    if single:
        models.append(single)
    raw_fallbacks = (os.getenv("OPENROUTER_FALLBACK_MODELS") or "").strip()
    if raw_fallbacks:
        models.extend([x.strip() for x in raw_fallbacks.split(",") if x.strip()])
    if not models:
        models.extend(DEFAULT_MODELS)

    # Deduplicate while preserving order.
    seen = set()
    result: List[str] = []
    for m in models:
        if m in seen:
            continue
        seen.add(m)
        result.append(m)
    return result


def stream_openrouter_summary_sync(prompt: str, on_delta) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    payload = {
        "temperature": 0.0,
        "max_tokens": 250,
        "stream": True,
        "messages": _messages_for_model(prompt),
    }

    models = _resolve_models()
    last_error = ""
    for model in models:
        model_payload = dict(payload, model=model)
        req = request.Request(
            OPENROUTER_URL,
            data=json.dumps(model_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://xyloz-tg-bot.local",
                "X-Title": "xyloz_tg_bot",
            },
            method="POST",
        )

        full_text = []
        try:
            with request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[5:].strip()
                    if payload_line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict) and chunk.get("error"):
                        last_error = f"{model}: {chunk.get('error')}"
                        break

                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if not delta:
                        continue
                    full_text.append(delta)
                    on_delta(delta)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model}: {exc.code} {details[:200]}"
            if exc.code in (404, 429):
                continue
            raise RuntimeError(f"LLM API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"LLM API недоступен: {exc.reason}")

        text = "".join(full_text).strip()
        if text:
            return text
        if not last_error:
            last_error = f"{model}: empty streamed content"

    raise RuntimeError(
        "Не найдено доступных endpoint'ов для моделей. "
        "Укажи рабочую модель в OPENROUTER_MODEL. "
        f"Последняя ошибка: {last_error or 'n/a'}"
    )


def _build_prompt(messages: List[ChatMessage], custom_task: str | None = None) -> str:
    selected, omitted = _fit_messages_to_token_budget(messages, MAX_INPUT_TOKENS)
    participants = sorted({m.author for m in selected if m.author})
    lines = [
        "Сделай краткий пересказ последних сообщений чата.",
        "Формат ответа (строго):",
        "1) Ключевые темы (2-4 пункта)",
        "2) Решения и договоренности",
        "3) Что осталось открытым",
        "4) Следующие действия (если есть)",
        "Ограничения ответа:",
        "- Максимум 6 коротких пунктов суммарно",
        "- Не перечисляй личные оскорбления и провокации",
        "- Не делай шутливых или саркастических формулировок",
        "- Не добавляй участников, которых нет во входных сообщениях",
        "- При неуверенности используй формулировку 'не удалось достоверно определить'",
        "",
        f"Допустимые участники: {', '.join(participants) if participants else 'не определены'}",
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
