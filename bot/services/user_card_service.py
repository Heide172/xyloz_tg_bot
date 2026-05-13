import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func

from common import prompts
from common.db.db import SessionLocal
from common.models.message import Message
from common.models.reaction import Reaction
from common.models.user import User
from services import ai_client
from services.summary_service import (
    MAX_CHARS_PER_MESSAGE,
    MAX_INPUT_TOKENS,
    _estimate_tokens,
    _truncate_text,
    get_summary_model,
)


CARD_MESSAGE_SAMPLE = 200
CARD_REACTION_TOP = 5


@dataclass
class UserCardStats:
    total_messages: int
    first_message_at: Optional[datetime]
    last_message_at: Optional[datetime]
    avg_message_chars: int
    reactions_received: list[tuple[str, int]] = field(default_factory=list)
    reactions_given: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class CardContext:
    user: User
    stats: UserCardStats
    sample_texts: list[str]


def resolve_user_for_card(
    chat_id: int,
    arg_text: str | None,
    fallback_tg_id: int | None,
    reply_to_tg_id: int | None,
) -> Optional[User]:
    """Возвращает User, для которого делается карточка.

    Приоритет: reply > @username из аргумента > msg.from_user.
    """
    session = SessionLocal()
    try:
        if reply_to_tg_id is not None:
            user = session.query(User).filter(User.tg_id == reply_to_tg_id).first()
            if user:
                return user

        if arg_text:
            match = re.search(r"@([A-Za-z0-9_]{3,32})", arg_text)
            if match:
                username = match.group(1)
                user = (
                    session.query(User)
                    .filter(func.lower(User.username) == username.lower())
                    .first()
                )
                if user:
                    return user

        if fallback_tg_id is not None:
            return session.query(User).filter(User.tg_id == fallback_tg_id).first()
        return None
    finally:
        session.close()


def _collect_stats(chat_id: int, user_id: int) -> UserCardStats:
    session = SessionLocal()
    try:
        base = session.query(Message).filter(
            Message.chat_id == chat_id,
            Message.user_id == user_id,
        )

        total = base.count()
        first_at = base.order_by(Message.created_at.asc()).limit(1).value(Message.created_at)
        last_at = base.order_by(Message.created_at.desc()).limit(1).value(Message.created_at)

        avg_chars_row = (
            session.query(func.avg(func.length(Message.text)))
            .filter(
                Message.chat_id == chat_id,
                Message.user_id == user_id,
                Message.text.isnot(None),
                Message.text != "",
            )
            .scalar()
        )
        avg_chars = int(avg_chars_row or 0)

        received_rows = (
            session.query(Reaction.emoji, func.count(Reaction.id))
            .join(Message, Reaction.message_id == Message.id)
            .filter(
                Message.chat_id == chat_id,
                Message.user_id == user_id,
                Reaction.emoji.isnot(None),
            )
            .group_by(Reaction.emoji)
            .order_by(func.count(Reaction.id).desc())
            .limit(CARD_REACTION_TOP)
            .all()
        )

        given_rows = (
            session.query(Reaction.emoji, func.count(Reaction.id))
            .join(Message, Reaction.message_id == Message.id)
            .filter(
                Message.chat_id == chat_id,
                Reaction.user_id == user_id,
                Reaction.emoji.isnot(None),
            )
            .group_by(Reaction.emoji)
            .order_by(func.count(Reaction.id).desc())
            .limit(CARD_REACTION_TOP)
            .all()
        )

        return UserCardStats(
            total_messages=total,
            first_message_at=first_at,
            last_message_at=last_at,
            avg_message_chars=avg_chars,
            reactions_received=[(e, c) for e, c in received_rows],
            reactions_given=[(e, c) for e, c in given_rows],
        )
    finally:
        session.close()


def _collect_sample_texts(chat_id: int, user_id: int) -> list[str]:
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.text)
            .filter(
                Message.chat_id == chat_id,
                Message.user_id == user_id,
                Message.text.isnot(None),
                Message.text != "",
            )
            .order_by(Message.created_at.desc())
            .limit(CARD_MESSAGE_SAMPLE)
            .all()
        )
        return [r[0].strip() for r in rows][::-1]
    finally:
        session.close()


def _author_label(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.fullname:
        return user.fullname
    return f"id{user.tg_id}"


def _fit_sample_to_budget(texts: list[str]) -> tuple[list[str], int]:
    clipped = [_truncate_text(t, MAX_CHARS_PER_MESSAGE) for t in texts]
    selected: list[str] = []
    used = 0
    budget = int(MAX_INPUT_TOKENS * 0.7)  # оставляем место под заголовок и инструкцию
    for t in reversed(clipped):
        line_tokens = _estimate_tokens(t)
        if used + line_tokens > budget:
            break
        selected.append(t)
        used += line_tokens
    selected.reverse()
    omitted = len(clipped) - len(selected)
    return selected, omitted


def _format_stats_header(user: User, stats: UserCardStats) -> str:
    first = stats.first_message_at.strftime("%Y-%m-%d") if stats.first_message_at else "—"
    last = stats.last_message_at.strftime("%Y-%m-%d") if stats.last_message_at else "—"
    received = ", ".join(f"{e}×{c}" for e, c in stats.reactions_received) or "—"
    given = ", ".join(f"{e}×{c}" for e, c in stats.reactions_given) or "—"
    return (
        f"Участник: {_author_label(user)}\n"
        f"Всего сообщений: {stats.total_messages}\n"
        f"Период активности: {first} — {last}\n"
        f"Средняя длина сообщения: {stats.avg_message_chars} симв.\n"
        f"Топ реакций, полученных пользователем: {received}\n"
        f"Топ реакций, поставленных пользователем: {given}"
    )


def _build_prompt(ctx: CardContext) -> str:
    sample, omitted = _fit_sample_to_budget(ctx.sample_texts)
    lines = [
        prompts.load("user_card_task"),
        "",
        _format_stats_header(ctx.user, ctx.stats),
        "",
        "Сэмпл сообщений участника (от старых к новым):",
    ]
    if omitted:
        lines.append(f"(Не показано {omitted} более старых сообщений из-за лимита контекста)")
    for t in sample:
        lines.append(f"- {t}")
    return "\n".join(lines)


async def stream_user_card(
    chat_id: int,
    user: User,
    on_delta=None,
    on_reasoning=None,
) -> tuple[str, str]:
    """Возвращает (header, llm_text). Если у юзера нет сообщений — llm_text="" и header содержит сообщение."""
    stats = await asyncio.to_thread(_collect_stats, chat_id, user.id)
    if stats.total_messages == 0:
        return f"У {_author_label(user)} нет сообщений в этом чате.", ""

    sample = await asyncio.to_thread(_collect_sample_texts, chat_id, user.id)
    ctx = CardContext(user=user, stats=stats, sample_texts=sample)
    prompt = _build_prompt(ctx)

    card_text = await asyncio.to_thread(
        ai_client.stream,
        prompt,
        get_summary_model(),
        on_delta or (lambda _d: None),
        prompts.load("user_card_system"),
        on_reasoning,
    )

    header_lines = ["🪪 Карточка участника", "", _format_stats_header(user, stats)]
    header = "\n".join(header_lines)
    return header, card_text


async def generate_user_card(chat_id: int, user: User) -> str:
    """Совместимость. Без stream-callback'ов."""
    header, content = await stream_user_card(chat_id, user)
    if not content:
        return header
    return f"{header}\n\n{content}"
