import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import func

from common import prompts
from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User
from services import ai_client
from services.summary_service import (
    MAX_CHARS_PER_MESSAGE,
    MAX_INPUT_TOKENS,
    ChatMessage,
    _estimate_tokens,
    _truncate_text,
    get_summary_model,
)


DIGEST_MIN_DAYS = 1
DIGEST_MAX_DAYS = 30
DIGEST_DEFAULT_DAYS = 7


@dataclass
class DigestStats:
    total_messages: int
    active_users: int
    top_authors: list[tuple[str, int]]
    period_start: datetime
    period_end: datetime


def parse_digest_days(command_text: str, default: int = DIGEST_DEFAULT_DAYS) -> int:
    parts = (command_text or "").split()
    if len(parts) < 2:
        return default
    try:
        value = int(parts[1])
    except ValueError:
        raise ValueError(f"Дни должны быть числом, пример: /digest 7")
    if value < DIGEST_MIN_DAYS or value > DIGEST_MAX_DAYS:
        raise ValueError(f"Дни должны быть в диапазоне {DIGEST_MIN_DAYS}..{DIGEST_MAX_DAYS}")
    return value


def _author_label(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


def _fetch_period_messages(chat_id: int, days: int) -> tuple[list[ChatMessage], DigestStats]:
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)

    session = SessionLocal()
    try:
        rows = (
            session.query(Message, User)
            .outerjoin(User, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .order_by(Message.created_at.asc())
            .all()
        )

        messages: list[ChatMessage] = []
        author_counts: dict[str, int] = {}
        unique_user_ids: set[int] = set()
        for msg, user in rows:
            author = _author_label(user)
            messages.append(ChatMessage(author=author, text=msg.text.strip()))
            author_counts[author] = author_counts.get(author, 0) + 1
            if msg.user_id is not None:
                unique_user_ids.add(msg.user_id)

        top_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        stats = DigestStats(
            total_messages=len(messages),
            active_users=len(unique_user_ids),
            top_authors=top_authors,
            period_start=period_start,
            period_end=period_end,
        )
        return messages, stats
    finally:
        session.close()


def _downsample(messages: list[ChatMessage], target_count: int) -> tuple[list[ChatMessage], int]:
    if len(messages) <= target_count:
        return messages, 0
    step = len(messages) / target_count
    sampled = [messages[min(int(i * step), len(messages) - 1)] for i in range(target_count)]
    return sampled, len(messages) - len(sampled)


def _fit_to_budget(messages: list[ChatMessage]) -> tuple[list[ChatMessage], int]:
    clipped = [
        ChatMessage(author=m.author, text=_truncate_text(m.text, MAX_CHARS_PER_MESSAGE))
        for m in messages
    ]

    avg_tokens = max(8, _estimate_tokens(" ".join(m.text for m in clipped[:50])) // max(1, min(50, len(clipped))))
    target = max(50, MAX_INPUT_TOKENS // avg_tokens)
    sampled, dropped_from_sample = _downsample(clipped, target)

    final: list[ChatMessage] = []
    used = 0
    for item in sampled:
        line = f"- {item.author}: {item.text}"
        tokens = _estimate_tokens(line)
        if used + tokens > MAX_INPUT_TOKENS:
            break
        final.append(item)
        used += tokens

    omitted = (len(clipped) - len(final))
    return final, omitted


def _format_period_header(stats: DigestStats, days: int) -> str:
    start = stats.period_start.strftime("%Y-%m-%d")
    end = stats.period_end.strftime("%Y-%m-%d")
    top_authors_line = ", ".join(f"{name} ({count})" for name, count in stats.top_authors) or "—"
    return (
        f"Период: {start} — {end} ({days} дн.)\n"
        f"Всего сообщений: {stats.total_messages}\n"
        f"Активных участников: {stats.active_users}\n"
        f"Топ авторов по объёму: {top_authors_line}"
    )


def _build_prompt(messages: list[ChatMessage], stats: DigestStats, days: int) -> str:
    fitted, omitted = _fit_to_budget(messages)
    lines = [
        prompts.load("digest_task"),
        "",
        _format_period_header(stats, days),
        "",
        "Сообщения (возможно, равномерно сэмплированы из всего объёма):",
    ]
    if omitted:
        lines.append(f"(Не показано: {omitted} сообщений из-за лимита контекста)")
    for item in fitted:
        lines.append(f"- {item.author}: {item.text}")
    return "\n".join(lines)


def has_data_for_period(chat_id: int, days: int) -> bool:
    period_start = datetime.utcnow() - timedelta(days=days)
    session = SessionLocal()
    try:
        count = (
            session.query(func.count(Message.id))
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .scalar()
        )
        return (count or 0) > 0
    finally:
        session.close()


def find_active_chat_ids(window_days: int = 14) -> list[int]:
    period_start = datetime.utcnow() - timedelta(days=window_days)
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.chat_id)
            .filter(Message.created_at >= period_start)
            .distinct()
            .all()
        )
        return [r[0] for r in rows]
    finally:
        session.close()


async def generate_digest(chat_id: int, days: int = DIGEST_DEFAULT_DAYS) -> str:
    messages, stats = await asyncio.to_thread(_fetch_period_messages, chat_id, days)
    if not messages:
        return f"За последние {days} дн. нет текстовых сообщений для дайджеста."

    prompt = _build_prompt(messages, stats, days)
    digest_text = await asyncio.to_thread(
        ai_client.call_yandex,
        prompt,
        get_summary_model(),
        prompts.load("digest_system"),
    )

    header = _format_period_header(stats, days)
    return f"📰 Дайджест чата\n\n{header}\n\n{digest_text}"
