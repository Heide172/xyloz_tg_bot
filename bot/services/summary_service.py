import asyncio
import json
import os
from dataclasses import dataclass
from typing import List
from urllib import error, request

from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct:free"
MAX_MESSAGES = 200


@dataclass
class ChatMessage:
    author: str
    text: str


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

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 250,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты делаешь краткий пересказ чата на русском. "
                    "Выделяй только суть, 4-7 пунктов, без воды."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    req = request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
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
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM API error: {exc.code} {details[:200]}")
    except error.URLError as exc:
        raise RuntimeError(f"LLM API недоступен: {exc.reason}")

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Некорректный ответ LLM API")


def stream_openrouter_summary_sync(prompt: str, on_delta) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 250,
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты делаешь краткий пересказ чата на русском. "
                    "Выделяй только суть, 4-7 пунктов, без воды."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    req = request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
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
        raise RuntimeError(f"LLM API error: {exc.code} {details[:200]}")
    except error.URLError as exc:
        raise RuntimeError(f"LLM API недоступен: {exc.reason}")

    text = "".join(full_text).strip()
    if not text:
        raise RuntimeError("Пустой ответ LLM API")
    return text


def _build_prompt(messages: List[ChatMessage]) -> str:
    lines = [
        "Сделай краткий пересказ последних сообщений чата.",
        "Формат:",
        "1) Тема обсуждения",
        "2) Ключевые решения/выводы",
        "3) Открытые вопросы",
        "",
        "Сообщения:",
    ]
    for item in messages:
        lines.append(f"- {item.author}: {item.text}")
    return "\n".join(lines)


async def summarize_recent_messages(chat_id: int, limit: int, exclude_message_id: int | None = None) -> str:
    messages = get_recent_text_messages(chat_id=chat_id, limit=limit, exclude_message_id=exclude_message_id)
    if not messages:
        return "Недостаточно данных: в чате нет текстовых сообщений для пересказа."

    prompt = _build_prompt(messages)
    summary = await asyncio.to_thread(_call_openrouter_sync, prompt)
    return summary


def build_summary_prompt(chat_id: int, limit: int, exclude_message_id: int | None = None) -> str:
    messages = get_recent_text_messages(chat_id=chat_id, limit=limit, exclude_message_id=exclude_message_id)
    if not messages:
        raise RuntimeError("Недостаточно данных: в чате нет текстовых сообщений для пересказа.")
    return _build_prompt(messages)
