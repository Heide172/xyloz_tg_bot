"""Ежедневные номинации.

Каждый день в 10:00 МСК для каждого активного чата подводим итоги вчерашнего дня:
- most_active: топ по числу сообщений
- most_toxic:  топ по avg toxicity_score (≥ MIN_MESSAGES)
- most_positive: топ по доле positive sentiment (≥ MIN_MESSAGES)
- best_quote: сообщение с max reactions (длиной ≥ MIN_QUOTE_CHARS)

Начисление идемпотентно: ref_id = "{kind}:{chat_id}:{YYYY-MM-DD}".
"""
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import case, func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.economy_tx import EconomyTx
from common.models.message import Message
from common.models.reaction import Reaction
from common.models.user import User
from services.economy_service import credit

logger = get_logger(__name__)

MSK = ZoneInfo("Europe/Moscow")

NOMINATION_PRIZE = int(os.getenv("NOMINATION_PRIZE", "300"))
NOMINATION_FAG = int(os.getenv("NOMINATION_FAG", "500"))
MIN_MESSAGES_FOR_SENTIMENT = int(os.getenv("NOMINATION_MIN_MESSAGES", "5"))
MIN_QUOTE_CHARS = int(os.getenv("NOMINATION_MIN_QUOTE_CHARS", "30"))
MIN_QUOTE_REACTIONS = int(os.getenv("NOMINATION_MIN_QUOTE_REACTIONS", "2"))
ACTIVE_CHAT_WINDOW_DAYS = int(os.getenv("NOMINATION_ACTIVE_WINDOW_DAYS", "14"))


@dataclass
class Nomination:
    chat_id: int
    kind: str
    user: User
    metric: str
    amount: int
    message_text: str | None = None


def _msk_day_range(day_msk: date) -> tuple[datetime, datetime]:
    """В БД created_at в session TZ Europe/Moscow (см. fix_fag day_window). Окно считаем как naive MSK."""
    start = datetime(day_msk.year, day_msk.month, day_msk.day)
    end = start + timedelta(days=1)
    return start, end


def _ref(kind: str, chat_id: int, day_msk: date) -> str:
    return f"{kind}:{chat_id}:{day_msk.isoformat()}"


def _already_awarded(session, ref_id: str) -> bool:
    return (
        session.query(EconomyTx.id)
        .filter(EconomyTx.ref_id == ref_id)
        .first()
        is not None
    )


def find_active_chats(window_days: int = ACTIVE_CHAT_WINDOW_DAYS) -> list[int]:
    since = datetime.utcnow() - timedelta(days=window_days)
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.chat_id)
            .filter(Message.created_at >= since)
            .distinct()
            .all()
        )
        return [int(r[0]) for r in rows]
    finally:
        session.close()


# ---------------- picks ----------------


def pick_most_active(chat_id: int, day_msk: date) -> tuple[User, int] | None:
    start, end = _msk_day_range(day_msk)
    session = SessionLocal()
    try:
        row = (
            session.query(User, func.count(Message.id).label("c"))
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= start,
                Message.created_at < end,
            )
            .group_by(User.id)
            .order_by(func.count(Message.id).desc())
            .first()
        )
        return (row[0], int(row[1])) if row else None
    finally:
        session.close()


def pick_most_toxic(chat_id: int, day_msk: date) -> tuple[User, float, int] | None:
    start, end = _msk_day_range(day_msk)
    session = SessionLocal()
    try:
        row = (
            session.query(
                User,
                func.avg(Message.toxicity_score).label("avg_t"),
                func.count(Message.id).label("c"),
            )
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= start,
                Message.created_at < end,
                Message.toxicity_score.isnot(None),
            )
            .group_by(User.id)
            .having(func.count(Message.id) >= MIN_MESSAGES_FOR_SENTIMENT)
            .order_by(func.avg(Message.toxicity_score).desc())
            .first()
        )
        return (row[0], float(row[1]), int(row[2])) if row else None
    finally:
        session.close()


def pick_most_positive(chat_id: int, day_msk: date) -> tuple[User, float, int] | None:
    start, end = _msk_day_range(day_msk)
    session = SessionLocal()
    try:
        total = func.count(Message.id).label("c")
        pos = func.sum(case((Message.sentiment_label == "positive", 1), else_=0)).label("p")
        row = (
            session.query(User, pos, total)
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= start,
                Message.created_at < end,
                Message.sentiment_label.isnot(None),
            )
            .group_by(User.id)
            .having(func.count(Message.id) >= MIN_MESSAGES_FOR_SENTIMENT)
            .order_by((pos / func.nullif(total, 0)).desc(), pos.desc())
            .first()
        )
        if not row:
            return None
        user, p, c = row
        share = float(int(p) / int(c)) if int(c) else 0.0
        return (user, share, int(c))
    finally:
        session.close()


def pick_best_quote(chat_id: int, day_msk: date) -> tuple[User, str, int] | None:
    start, end = _msk_day_range(day_msk)
    session = SessionLocal()
    try:
        row = (
            session.query(
                User,
                Message.text,
                func.count(Reaction.id).label("rc"),
            )
            .join(Message, Message.user_id == User.id)
            .join(Reaction, Reaction.message_id == Message.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= start,
                Message.created_at < end,
                Message.text.isnot(None),
                func.length(Message.text) >= MIN_QUOTE_CHARS,
            )
            .group_by(User.id, Message.id, Message.text)
            .having(func.count(Reaction.id) >= MIN_QUOTE_REACTIONS)
            .order_by(func.count(Reaction.id).desc())
            .first()
        )
        if not row:
            return None
        return (row[0], row[1], int(row[2]))
    finally:
        session.close()


# ---------------- award + post ----------------


def _award_if_new(chat_id: int, user_id: int, kind: str, day_msk: date, amount: int, note: str) -> bool:
    """Возвращает True если только что начислили; False если уже было."""
    ref_id = _ref(kind, chat_id, day_msk)
    session = SessionLocal()
    try:
        if _already_awarded(session, ref_id):
            return False
    finally:
        session.close()
    credit(user_id=user_id, chat_id=chat_id, amount=amount, kind=kind, ref_id=ref_id, note=note)
    return True


def _author_name(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


def collect_nominations_for_chat(chat_id: int, day_msk: date) -> list[Nomination]:
    nominations: list[Nomination] = []

    active = pick_most_active(chat_id, day_msk)
    if active:
        user, cnt = active
        nominations.append(Nomination(
            chat_id=chat_id,
            kind="nomination_most_active",
            user=user,
            metric=f"{cnt} сообщений",
            amount=NOMINATION_PRIZE,
        ))

    toxic = pick_most_toxic(chat_id, day_msk)
    if toxic:
        user, avg_t, cnt = toxic
        nominations.append(Nomination(
            chat_id=chat_id,
            kind="nomination_most_toxic",
            user=user,
            metric=f"avg tox {avg_t:.2f} (по {cnt} сообщ.)",
            amount=NOMINATION_PRIZE,
        ))

    positive = pick_most_positive(chat_id, day_msk)
    if positive:
        user, share, cnt = positive
        nominations.append(Nomination(
            chat_id=chat_id,
            kind="nomination_most_positive",
            user=user,
            metric=f"positive {share*100:.0f}% (по {cnt} сообщ.)",
            amount=NOMINATION_PRIZE,
        ))

    quote = pick_best_quote(chat_id, day_msk)
    if quote:
        user, text, rc = quote
        clipped = (text or "").strip().replace("\n", " ")
        if len(clipped) > 200:
            clipped = clipped[:200] + "…"
        nominations.append(Nomination(
            chat_id=chat_id,
            kind="nomination_best_quote",
            user=user,
            metric=f"{rc} реакций",
            amount=NOMINATION_PRIZE,
            message_text=clipped,
        ))

    return nominations


def _format_summary(chat_id: int, day_msk: date, nominations: list[Nomination], awarded_count: int) -> str:
    lines = [f"Номинации за {day_msk.strftime('%Y-%m-%d')} (MSK)", ""]
    if not nominations:
        lines.append("Никого: вчера в чате не было активности.")
        return "\n".join(lines)
    for n in nominations:
        title_map = {
            "nomination_most_active": "Самый активный",
            "nomination_most_toxic": "Самый токсичный",
            "nomination_most_positive": "Главный позитив",
            "nomination_best_quote": "Лучшая цитата",
        }
        title = title_map.get(n.kind, n.kind)
        lines.append(f"{title}: {_author_name(n.user)}  +{n.amount} гривен  ({n.metric})")
        if n.message_text:
            lines.append(f'  «{n.message_text}»')
    if awarded_count < len(nominations):
        lines.append("")
        lines.append(f"(Часть номинаций ({len(nominations) - awarded_count}) уже была начислена раньше — не дублировал.)")
    return "\n".join(lines)


async def run_daily_nominations(bot: Bot) -> None:
    """Подвести итоги вчерашнего MSK-дня для каждого активного чата, начислить и запостить."""
    yesterday = datetime.now(tz=MSK).date() - timedelta(days=1)
    chat_ids = find_active_chats()
    logger.info("nominations: %d active chats, day=%s", len(chat_ids), yesterday)
    for chat_id in chat_ids:
        try:
            nominations = collect_nominations_for_chat(chat_id, yesterday)
            if not nominations:
                continue
            awarded = 0
            for n in nominations:
                ok = _award_if_new(
                    chat_id=n.chat_id,
                    user_id=n.user.id,
                    kind=n.kind,
                    day_msk=yesterday,
                    amount=n.amount,
                    note=n.metric,
                )
                if ok:
                    awarded += 1
            text = _format_summary(chat_id, yesterday, nominations, awarded)
            try:
                await bot.send_message(chat_id, text)
            except Exception:
                logger.exception("nominations: failed to post in chat %s", chat_id)
        except Exception:
            logger.exception("nominations: failed for chat %s", chat_id)


# ---------------- award /fag ----------------


def award_fag(chat_id: int, user_id: int, day_msk: date) -> int | None:
    """Начисляет бонус победителю /fag за день. Возвращает сумму или None если уже было."""
    ref_id = _ref("nomination_fag", chat_id, day_msk)
    session = SessionLocal()
    try:
        if _already_awarded(session, ref_id):
            return None
    finally:
        session.close()
    credit(user_id=user_id, chat_id=chat_id, amount=NOMINATION_FAG, kind="nomination_fag", ref_id=ref_id, note=f"fag of {day_msk.isoformat()}")
    return NOMINATION_FAG
