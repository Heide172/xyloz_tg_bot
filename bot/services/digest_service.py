import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

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


DIGEST_MIN_DAYS = 1
DIGEST_MAX_DAYS = 30
DIGEST_DEFAULT_DAYS = 7

BURST_TOP_K = 3
BURST_MIN_HOUR_COUNT = 8
BURST_MEDIAN_MULTIPLIER = 2.5
BURST_SAMPLE_PER_WINDOW = 25
BACKGROUND_SAMPLE_LIMIT = 80
TOP_AUTHOR_LIMIT = 5

MSK = ZoneInfo("Europe/Moscow")


@dataclass
class RawMessage:
    created_at: datetime
    author: str
    text: str
    reactions: int


@dataclass
class BurstWindow:
    start: datetime
    end: datetime  # эксклюзивная граница (start + N часов)
    count: int
    top_authors: list[tuple[str, int]]
    sample: list[RawMessage]


@dataclass
class DigestData:
    days: int
    period_start: datetime
    period_end: datetime
    total_messages: int
    active_users: int
    top_authors: list[tuple[str, int]]
    bursts: list[BurstWindow]
    background_sample: list[RawMessage]
    background_total: int


def parse_digest_days(command_text: str, default: int = DIGEST_DEFAULT_DAYS) -> int:
    parts = (command_text or "").split()
    if len(parts) < 2:
        return default
    try:
        value = int(parts[1])
    except ValueError:
        raise ValueError("Дни должны быть числом, пример: /digest 7")
    if value < DIGEST_MIN_DAYS or value > DIGEST_MAX_DAYS:
        raise ValueError(f"Дни должны быть в диапазоне {DIGEST_MIN_DAYS}..{DIGEST_MAX_DAYS}")
    return value


def _author_label(username: str | None, fullname: str | None) -> str:
    if username:
        return f"@{username}"
    if fullname:
        return fullname
    return "Unknown"


def _to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def _fetch_period_messages(chat_id: int, days: int) -> tuple[list[RawMessage], datetime, datetime]:
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)

    session = SessionLocal()
    try:
        react_count = func.count(Reaction.id).label("react_count")
        rows = (
            session.query(
                Message.created_at,
                User.username,
                User.fullname,
                Message.text,
                react_count,
            )
            .outerjoin(User, Message.user_id == User.id)
            .outerjoin(Reaction, Reaction.message_id == Message.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .group_by(Message.id, User.username, User.fullname)
            .order_by(Message.created_at.asc())
            .all()
        )

        messages = [
            RawMessage(
                created_at=row.created_at,
                author=_author_label(row.username, row.fullname),
                text=row.text.strip(),
                reactions=int(row.react_count or 0),
            )
            for row in rows
        ]
        return messages, period_start, period_end
    finally:
        session.close()


def _find_burst_windows(messages: list[RawMessage]) -> list[tuple[datetime, datetime]]:
    """Возвращает merged горячие окна как (start_hour, end_hour_exclusive)."""
    if not messages:
        return []

    buckets: dict[datetime, int] = {}
    for m in messages:
        h = m.created_at.replace(minute=0, second=0, microsecond=0)
        buckets[h] = buckets.get(h, 0) + 1

    counts = sorted(buckets.values())
    median = counts[len(counts) // 2] if counts else 0
    threshold = max(BURST_MIN_HOUR_COUNT, int(median * BURST_MEDIAN_MULTIPLIER))

    hot = sorted(
        ((h, c) for h, c in buckets.items() if c >= threshold),
        key=lambda x: x[0],
    )
    if not hot:
        return []

    # merge adjacent hours into windows
    merged: list[list] = []  # [start, end_exclusive, total_count]
    one_hour = timedelta(hours=1)
    for h, c in hot:
        if merged and h == merged[-1][1]:
            merged[-1][1] = h + one_hour
            merged[-1][2] += c
        else:
            merged.append([h, h + one_hour, c])

    merged.sort(key=lambda w: -w[2])
    top = merged[:BURST_TOP_K]
    top.sort(key=lambda w: w[0])
    return [(w[0], w[1]) for w in top]


def _clip(text: str, limit: int = MAX_CHARS_PER_MESSAGE) -> str:
    return _truncate_text(text.replace("\n", " "), limit)


def _build_burst(messages: list[RawMessage], window: tuple[datetime, datetime]) -> BurstWindow:
    start, end = window
    in_window = [m for m in messages if start <= m.created_at < end]

    author_counts = Counter(m.author for m in in_window)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)

    # сэмпл: сначала по числу реакций, затем по хронологии
    sorted_by_reactions = sorted(in_window, key=lambda m: (-m.reactions, m.created_at))
    sample = sorted_by_reactions[:BURST_SAMPLE_PER_WINDOW]
    sample.sort(key=lambda m: m.created_at)

    return BurstWindow(
        start=start,
        end=end,
        count=len(in_window),
        top_authors=top_authors,
        sample=sample,
    )


def _build_background_sample(messages: list[RawMessage], burst_windows: list[tuple[datetime, datetime]]) -> tuple[list[RawMessage], int]:
    def in_any_burst(m: RawMessage) -> bool:
        for s, e in burst_windows:
            if s <= m.created_at < e:
                return True
        return False

    background = [m for m in messages if not in_any_burst(m)]
    total = len(background)
    if total <= BACKGROUND_SAMPLE_LIMIT:
        return background, total

    step = total / BACKGROUND_SAMPLE_LIMIT
    sampled = [background[min(int(i * step), total - 1)] for i in range(BACKGROUND_SAMPLE_LIMIT)]
    sampled.sort(key=lambda m: m.created_at)
    return sampled, total


def _build_digest_data(messages: list[RawMessage], period_start: datetime, period_end: datetime, days: int) -> DigestData:
    author_counts = Counter(m.author for m in messages)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)
    active_users = len(author_counts)

    burst_windows = _find_burst_windows(messages)
    bursts = [_build_burst(messages, w) for w in burst_windows]
    background, background_total = _build_background_sample(messages, burst_windows)

    return DigestData(
        days=days,
        period_start=period_start,
        period_end=period_end,
        total_messages=len(messages),
        active_users=active_users,
        top_authors=top_authors,
        bursts=bursts,
        background_sample=background,
        background_total=background_total,
    )


def _format_msg_line(m: RawMessage, include_date: bool) -> str:
    ts_msk = _to_msk(m.created_at)
    stamp = ts_msk.strftime("%m-%d %H:%M") if include_date else ts_msk.strftime("%H:%M")
    reactions = f" 👍×{m.reactions}" if m.reactions else ""
    return f"  {stamp} {m.author}{reactions}: {_clip(m.text)}"


def _format_authors(top_authors: list[tuple[str, int]]) -> str:
    if not top_authors:
        return "—"
    return ", ".join(f"{name} ({cnt})" for name, cnt in top_authors)


def _format_header(data: DigestData) -> str:
    start_msk = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end_msk = _to_msk(data.period_end).strftime("%Y-%m-%d")
    return (
        f"Период: {start_msk} — {end_msk} ({data.days} дн.), часовой пояс МСК\n"
        f"Всего сообщений: {data.total_messages} | Активных участников: {data.active_users}\n"
        f"Топ авторов: {_format_authors(data.top_authors)}"
    )


def _build_prompt(data: DigestData) -> str:
    lines: list[str] = [prompts.load("digest_task"), "", _format_header(data), ""]

    if not data.bursts:
        lines.append("Горячих окон активности не обнаружено — чат шёл ровно.")
        lines.append("")
    else:
        for i, burst in enumerate(data.bursts, 1):
            start_msk = _to_msk(burst.start).strftime("%Y-%m-%d %H:%M")
            end_msk = _to_msk(burst.end).strftime("%H:%M")
            lines.append(f"=== BURST {i}: {start_msk} — {end_msk} МСК | {burst.count} сообщ. ===")
            lines.append(f"Доминировали: {_format_authors(burst.top_authors)}")
            lines.append(f"Сэмпл (отсортирован по числу реакций, потом хронологически):")
            for m in burst.sample:
                lines.append(_format_msg_line(m, include_date=False))
            lines.append("")

    bg_label = f"=== ФОН (выборка {len(data.background_sample)} из {data.background_total} сообщений вне горячих окон) ==="
    lines.append(bg_label)
    if not data.background_sample:
        lines.append("  (вне горячих окон сообщений не было)")
    else:
        for m in data.background_sample:
            lines.append(_format_msg_line(m, include_date=True))

    text = "\n".join(lines)
    # Жёсткий клип по токенному бюджету (на всякий случай)
    if _estimate_tokens(text) > MAX_INPUT_TOKENS:
        # отрезаем фон агрессивнее
        while data.background_sample and _estimate_tokens("\n".join(lines)) > MAX_INPUT_TOKENS:
            lines.pop(-1)
        text = "\n".join(lines)
    return text


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


def _format_summary_header(data: DigestData) -> str:
    start_msk = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end_msk = _to_msk(data.period_end).strftime("%Y-%m-%d")
    lines = [
        f"📰 Дайджест чата",
        "",
        f"Период: {start_msk} — {end_msk} ({data.days} дн.)",
        f"Всего сообщений: {data.total_messages} | Активных участников: {data.active_users}",
        f"Топ авторов: {_format_authors(data.top_authors)}",
    ]
    if data.bursts:
        burst_summaries = []
        for i, b in enumerate(data.bursts, 1):
            start_msk = _to_msk(b.start).strftime("%m-%d %H:%M")
            end_msk = _to_msk(b.end).strftime("%H:%M")
            burst_summaries.append(f"BURST {i} {start_msk}–{end_msk} ({b.count})")
        lines.append(f"Горячие окна: {' · '.join(burst_summaries)}")
    return "\n".join(lines)


async def generate_digest(chat_id: int, days: int = DIGEST_DEFAULT_DAYS) -> str:
    messages, period_start, period_end = await asyncio.to_thread(_fetch_period_messages, chat_id, days)
    if not messages:
        return f"За последние {days} дн. нет текстовых сообщений для дайджеста."

    data = _build_digest_data(messages, period_start, period_end, days)
    prompt = _build_prompt(data)

    digest_text = await asyncio.to_thread(
        ai_client.call_yandex,
        prompt,
        get_summary_model(),
        prompts.load("digest_system"),
    )

    header = _format_summary_header(data)
    return f"{header}\n\n{digest_text}"
