from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import Counter
from io import BytesIO
from typing import Optional, Dict, List, Tuple

from sqlalchemy import func, and_
from sqlalchemy.orm import aliased

from common.db.db import SessionLocal
from common.models.message import Message
from common.models.user import User
from common.models.reaction import Reaction


@dataclass
class DailyPoint:
    day: str         # "YYYY-MM-DD"
    count: int


@dataclass
class UserStats:
    tg_id: int
    username: Optional[str]
    fullname: Optional[str]

    from_dt: datetime
    to_dt: datetime
    chat_id: Optional[int]

    total_messages: int
    text_messages: int
    stickers: int
    media: int

    replies_sent: int
    replies_received: int

    favorite_emoji: Optional[str]
    emoji_top: List[Tuple[str, int]]

    reactions_given: int
    favorite_reaction: Optional[str]

    # ВНИМАНИЕ: reactions_received может быть неточным, см. комментарий ниже
    reactions_received: int

    activity_daily: List[DailyPoint]


@dataclass
class GlobalStats:
    from_dt: datetime
    to_dt: datetime
    chat_id: Optional[int]

    total_messages: int
    unique_users: int

    replies_total: int
    stickers_total: int
    media_total: int

    top_users: List[Tuple[int, int]]  # (tg_id, message_count)
    activity_daily: List[DailyPoint]


def _normalize_range(days: int | None, from_dt: datetime | None, to_dt: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    if to_dt is None:
        to_dt = now
    if from_dt is None:
        if days is None:
            days = 30
        from_dt = to_dt - timedelta(days=days)
    return from_dt, to_dt


def _daily_activity_query(session, chat_id: Optional[int], from_dt: datetime, to_dt: datetime, user_db_id: Optional[int] = None):
    q = session.query(
        func.date(Message.created_at).label("day"),
        func.count(Message.id).label("cnt")
    ).filter(
        Message.created_at >= from_dt,
        Message.created_at <= to_dt,
    )

    if chat_id is not None:
        q = q.filter(Message.chat_id == chat_id)
    if user_db_id is not None:
        q = q.filter(Message.user_id == user_db_id)

    q = q.group_by(func.date(Message.created_at)).order_by(func.date(Message.created_at))
    return [(str(day), int(cnt)) for day, cnt in q.all()]


def _favorite_emoji_from_messages(session, chat_id: Optional[int], from_dt: datetime, to_dt: datetime, user_db_id: int) -> tuple[Optional[str], List[Tuple[str, int]]]:
    q = session.query(Message.emojis).filter(
        Message.user_id == user_db_id,
        Message.created_at >= from_dt,
        Message.created_at <= to_dt,
        Message.emojis.isnot(None),
        Message.emojis != "",
    )
    if chat_id is not None:
        q = q.filter(Message.chat_id == chat_id)

    counter = Counter()
    for (emo_str,) in q.all():
        # В БД у вас сохраняются эмодзи как строка из символов.
        # Считаем “по символам” — для сложных эмодзи-секвенций может быть неточно, но без изменения БД это максимум.
        counter.update(list(emo_str))

    if not counter:
        return None, []

    top = counter.most_common(10)
    return top[0][0], top


def _replies_sent(session, chat_id: Optional[int], from_dt: datetime, to_dt: datetime, user_db_id: int) -> int:
    q = session.query(func.count(Message.id)).filter(
        Message.user_id == user_db_id,
        Message.created_at >= from_dt,
        Message.created_at <= to_dt,
        Message.reply_to.isnot(None),
    )
    if chat_id is not None:
        q = q.filter(Message.chat_id == chat_id)
    return int(q.scalar() or 0)


def _replies_received(session, chat_id: Optional[int], from_dt: datetime, to_dt: datetime, user_db_id: int) -> int:
    # m2.reply_to == m1.telegram_message_id в том же chat_id
    m1 = aliased(Message)
    m2 = aliased(Message)

    q = session.query(func.count(m2.id)).filter(
        m1.user_id == user_db_id,
        m2.reply_to == m1.telegram_message_id,
        m2.chat_id == m1.chat_id,
        m2.created_at >= from_dt,
        m2.created_at <= to_dt,
    )

    if chat_id is not None:
        q = q.filter(m1.chat_id == chat_id).filter(m2.chat_id == chat_id)

    # Защитимся от NULL telegram_message_id (на всякий)
    q = q.filter(m1.telegram_message_id.isnot(None))
    return int(q.scalar() or 0)


def _reactions_given(session, from_dt: datetime, to_dt: datetime, user_db_id: int) -> tuple[int, Optional[str]]:
    # Reaction.user_id = кто поставил реакцию
    q = session.query(Reaction.emoji).filter(
        Reaction.user_id == user_db_id,
        # В вашей модели Reaction нет timestamp.
        # Поэтому "по диапазону" отфильтровать нельзя без доработки БД.
        # Оставляем как "за всё время" — честно.
    )

    counter = Counter([emoji for (emoji,) in q.all() if emoji])
    total = sum(counter.values())

    fav = counter.most_common(1)[0][0] if counter else None
    return int(total), fav


def _reactions_received_approx(session, chat_id: Optional[int], from_dt: datetime, to_dt: datetime, user_db_id: int) -> int:
    """
    ВНИМАНИЕ: Reaction не хранит chat_id, а message_id в Telegram уникален только внутри чата.
    Поэтому точное сопоставление по всем чатам невозможно без доработки БД.

    Если у вас бот в одном чате — будет ок.
    Если в нескольких — могут быть коллизии.
    """
    # Берем telegram_message_id сообщений пользователя за период, потом считаем Reaction.message_id по ним.
    q_msg = session.query(Message.telegram_message_id).filter(
        Message.user_id == user_db_id,
        Message.created_at >= from_dt,
        Message.created_at <= to_dt,
        Message.telegram_message_id.isnot(None),
    )
    if chat_id is not None:
        q_msg = q_msg.filter(Message.chat_id == chat_id)

    ids = [mid for (mid,) in q_msg.all()]
    if not ids:
        return 0

    q_react = session.query(func.count(Reaction.id)).filter(Reaction.message_id.in_(ids))
    return int(q_react.scalar() or 0)


def get_user_stats(
    tg_id: int,
    chat_id: Optional[int] = None,
    days: Optional[int] = 30,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> UserStats:
    from_dt, to_dt = _normalize_range(days, from_dt, to_dt)

    session = SessionLocal()
    try:
        user = session.query(User).filter(User.tg_id == tg_id).first()
        if not user:
            # пользователь ещё не писал — вернем "пустую" статистику
            return UserStats(
                tg_id=tg_id,
                username=None,
                fullname=None,
                from_dt=from_dt,
                to_dt=to_dt,
                chat_id=chat_id,
                total_messages=0,
                text_messages=0,
                stickers=0,
                media=0,
                replies_sent=0,
                replies_received=0,
                favorite_emoji=None,
                emoji_top=[],
                reactions_given=0,
                favorite_reaction=None,
                reactions_received=0,
                activity_daily=[],
            )

        base = session.query(Message).filter(
            Message.user_id == user.id,
            Message.created_at >= from_dt,
            Message.created_at <= to_dt,
        )
        if chat_id is not None:
            base = base.filter(Message.chat_id == chat_id)

        total_messages = int(base.count())
        text_messages = int(base.filter(Message.text.isnot(None), Message.text != "").count())
        stickers = int(base.filter(Message.sticker.isnot(None)).count())
        media = int(base.filter(Message.media.isnot(None)).count())

        activity = _daily_activity_query(session, chat_id, from_dt, to_dt, user_db_id=user.id)
        activity_daily = [DailyPoint(day=d, count=c) for d, c in activity]

        fav_emoji, emoji_top = _favorite_emoji_from_messages(session, chat_id, from_dt, to_dt, user.id)

        replies_sent = _replies_sent(session, chat_id, from_dt, to_dt, user.id)
        replies_received = _replies_received(session, chat_id, from_dt, to_dt, user.id)

        reactions_given, favorite_reaction = _reactions_given(session, from_dt, to_dt, user.id)
        reactions_received = _reactions_received_approx(session, chat_id, from_dt, to_dt, user.id)

        return UserStats(
            tg_id=user.tg_id,
            username=user.username,
            fullname=user.fullname,
            from_dt=from_dt,
            to_dt=to_dt,
            chat_id=chat_id,
            total_messages=total_messages,
            text_messages=text_messages,
            stickers=stickers,
            media=media,
            replies_sent=replies_sent,
            replies_received=replies_received,
            favorite_emoji=fav_emoji,
            emoji_top=emoji_top,
            reactions_given=reactions_given,
            favorite_reaction=favorite_reaction,
            reactions_received=reactions_received,
            activity_daily=activity_daily,
        )
    finally:
        session.close()


def get_global_stats(
    chat_id: Optional[int] = None,
    days: Optional[int] = 30,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    top_n: int = 10,
) -> GlobalStats:
    from_dt, to_dt = _normalize_range(days, from_dt, to_dt)

    session = SessionLocal()
    try:
        base = session.query(Message).filter(
            Message.created_at >= from_dt,
            Message.created_at <= to_dt,
        )
        if chat_id is not None:
            base = base.filter(Message.chat_id == chat_id)

        total_messages = int(base.count())
        unique_users = int(base.with_entities(func.count(func.distinct(Message.user_id))).scalar() or 0)

        replies_total = int(base.filter(Message.reply_to.isnot(None)).count())
        stickers_total = int(base.filter(Message.sticker.isnot(None)).count())
        media_total = int(base.filter(Message.media.isnot(None)).count())

        activity = _daily_activity_query(session, chat_id, from_dt, to_dt, user_db_id=None)
        activity_daily = [DailyPoint(day=d, count=c) for d, c in activity]

        # топ пользователей по количеству сообщений
        q_top = session.query(
            User.tg_id,
            func.count(Message.id).label("cnt")
        ).join(Message, Message.user_id == User.id).filter(
            Message.created_at >= from_dt,
            Message.created_at <= to_dt,
        )
        if chat_id is not None:
            q_top = q_top.filter(Message.chat_id == chat_id)

        q_top = q_top.group_by(User.tg_id).order_by(func.count(Message.id).desc()).limit(top_n)
        top_users = [(int(tg_id), int(cnt)) for tg_id, cnt in q_top.all()]

        return GlobalStats(
            from_dt=from_dt,
            to_dt=to_dt,
            chat_id=chat_id,
            total_messages=total_messages,
            unique_users=unique_users,
            replies_total=replies_total,
            stickers_total=stickers_total,
            media_total=media_total,
            top_users=top_users,
            activity_daily=activity_daily,
        )
    finally:
        session.close()


# ---------- график активности ----------

def render_activity_plot_png(points: List[DailyPoint], title: str = "Активность по дням") -> bytes:
    """
    Возвращает PNG bytes. Без seaborn, чистый matplotlib.
    """
    import matplotlib.pyplot as plt

    x = [p.day for p in points]
    y = [p.count for p in points]

    fig = plt.figure()
    plt.plot(x, y)
    plt.xticks(rotation=45, ha="right")
    plt.title(title)
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    return buf.getvalue()
