from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func

from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User


MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7
TOXIC_THRESHOLD = 0.5
TOP_LIMIT = 5
_BLOCKS = "▁▂▃▄▅▆▇█"


@dataclass
class MoodCounts:
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    unclassified: int = 0

    @property
    def total(self) -> int:
        return self.positive + self.neutral + self.negative

    def pct(self, value: int) -> float:
        if self.total == 0:
            return 0.0
        return 100.0 * value / self.total


def parse_days(command_text: str, default: int = DEFAULT_DAYS) -> int:
    parts = (command_text or "").split()
    if len(parts) < 2:
        return default
    try:
        value = int(parts[1])
    except ValueError:
        raise ValueError("Дни должны быть числом, пример: /mood 7")
    if value < MIN_DAYS or value > MAX_DAYS:
        raise ValueError(f"Дни должны быть в диапазоне {MIN_DAYS}..{MAX_DAYS}")
    return value


def _author_label(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


def _sparkline(values: list[int]) -> str:
    if not values:
        return "—"
    lo = min(values)
    hi = max(values)
    if hi == lo:
        idx = len(_BLOCKS) // 2
        return _BLOCKS[idx] * len(values)
    span = hi - lo
    chars = []
    for v in values:
        rel = (v - lo) / span
        idx = min(len(_BLOCKS) - 1, max(0, int(rel * (len(_BLOCKS) - 1))))
        chars.append(_BLOCKS[idx])
    return "".join(chars)


def _collect_counts(chat_id: int, period_start: datetime) -> MoodCounts:
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.sentiment_label, func.count(Message.id))
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .group_by(Message.sentiment_label)
            .all()
        )
        c = MoodCounts()
        for label, cnt in rows:
            if label == "positive":
                c.positive = cnt
            elif label == "negative":
                c.negative = cnt
            elif label == "neutral":
                c.neutral = cnt
            else:
                c.unclassified = cnt
        return c
    finally:
        session.close()


def _daily_net(chat_id: int, days: int) -> list[int]:
    period_start = datetime.utcnow() - timedelta(days=days)
    session = SessionLocal()
    try:
        rows = (
            session.query(
                func.date(Message.created_at).label("d"),
                func.sum(case((Message.sentiment_label == "positive", 1), else_=0)).label("p"),
                func.sum(case((Message.sentiment_label == "negative", 1), else_=0)).label("n"),
            )
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
            )
            .group_by("d")
            .order_by("d")
            .all()
        )
        by_day = {r[0]: int((r[1] or 0) - (r[2] or 0)) for r in rows}
        out: list[int] = []
        for i in range(days):
            day = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
            out.append(by_day.get(day, 0))
        return out
    finally:
        session.close()


def _top_authors_by_sentiment(chat_id: int, period_start: datetime, label: str) -> list[tuple[str, int]]:
    session = SessionLocal()
    try:
        rows = (
            session.query(User, func.count(Message.id))
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.sentiment_label == label,
            )
            .group_by(User.id)
            .order_by(func.count(Message.id).desc())
            .limit(TOP_LIMIT)
            .all()
        )
        return [(_author_label(u), int(c)) for u, c in rows]
    finally:
        session.close()


def build_mood_report(chat_id: int, days: int) -> str:
    period_start = datetime.utcnow() - timedelta(days=days)
    counts = _collect_counts(chat_id, period_start)
    if counts.total == 0:
        return f"За последние {days} дн. нет классифицированных сообщений."

    sparkline = _sparkline(_daily_net(chat_id, days))
    top_pos = _top_authors_by_sentiment(chat_id, period_start, "positive")
    top_neg = _top_authors_by_sentiment(chat_id, period_start, "negative")

    pos = f"{counts.positive} ({counts.pct(counts.positive):.0f}%)"
    neu = f"{counts.neutral} ({counts.pct(counts.neutral):.0f}%)"
    neg = f"{counts.negative} ({counts.pct(counts.negative):.0f}%)"

    lines = [
        f"😀 Настроение чата за {days} дн.",
        "",
        f"Всего классифицировано: {counts.total}" + (f" (ещё {counts.unclassified} ждут классификации)" if counts.unclassified else ""),
        f"Положительные: {pos}",
        f"Нейтральные: {neu}",
        f"Отрицательные: {neg}",
        "",
        f"Динамика по дням (pos − neg): {sparkline}",
        "",
        "Топ позитивных авторов:",
    ]
    if top_pos:
        for name, cnt in top_pos:
            lines.append(f"  • {name}: +{cnt}")
    else:
        lines.append("  —")
    lines.append("")
    lines.append("Топ негативных авторов:")
    if top_neg:
        for name, cnt in top_neg:
            lines.append(f"  • {name}: −{cnt}")
    else:
        lines.append("  —")
    return "\n".join(lines)


def build_toxic_report(chat_id: int, days: int) -> str:
    period_start = datetime.utcnow() - timedelta(days=days)
    session = SessionLocal()
    try:
        toxic_count = (
            session.query(func.count(Message.id))
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.toxicity_score >= TOXIC_THRESHOLD,
            )
            .scalar()
            or 0
        )
        total_classified = (
            session.query(func.count(Message.id))
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.toxicity_score.isnot(None),
            )
            .scalar()
            or 0
        )

        top_authors = (
            session.query(
                User,
                func.avg(Message.toxicity_score).label("avg_tox"),
                func.count(Message.id).label("cnt"),
            )
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.toxicity_score.isnot(None),
            )
            .group_by(User.id)
            .having(func.count(Message.id) >= 5)
            .order_by(func.avg(Message.toxicity_score).desc())
            .limit(TOP_LIMIT)
            .all()
        )

        top_messages = (
            session.query(Message, User)
            .outerjoin(User, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.toxicity_score >= TOXIC_THRESHOLD,
                Message.text.isnot(None),
                Message.text != "",
            )
            .order_by(Message.toxicity_score.desc())
            .limit(TOP_LIMIT)
            .all()
        )
    finally:
        session.close()

    if total_classified == 0:
        return f"За последние {days} дн. нет классифицированных сообщений."

    pct = 100.0 * toxic_count / total_classified
    lines = [
        f"☠️ Токсичность чата за {days} дн.",
        "",
        f"Сообщений с уровнем токсичности ≥ {TOXIC_THRESHOLD:.1f}: {toxic_count} из {total_classified} ({pct:.1f}%)",
        "",
        "Топ авторов по среднему уровню токсичности (≥5 сообщений):",
    ]
    if top_authors:
        for user, avg_tox, cnt in top_authors:
            lines.append(f"  • {_author_label(user)}: {float(avg_tox):.2f} (по {cnt} сообщ.)")
    else:
        lines.append("  —")
    lines.append("")
    lines.append("Самые токсичные сообщения:")
    if top_messages:
        for msg, user in top_messages:
            text = (msg.text or "").strip().replace("\n", " ")
            if len(text) > 120:
                text = text[:117] + "…"
            lines.append(f"  • [{float(msg.toxicity_score):.2f}] {_author_label(user)}: {text}")
    else:
        lines.append("  —")
    return "\n".join(lines)
