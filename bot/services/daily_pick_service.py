from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import distinct

from common.db.db import SessionLocal, engine
from common.models.daily_pick import DailyPick
from common.models.message import Message
from common.models.user import User


MSK = ZoneInfo("Europe/Moscow")
TITLE_PARTICIPANT_OF_DAY = "participant_of_day"


@dataclass
class PickResult:
    day_msk: date
    candidates_day_msk: date
    winner_tg_id: int
    winner_username: str | None
    winner_fullname: str | None
    is_new: bool


def _ensure_table():
    DailyPick.__table__.create(bind=engine, checkfirst=True)


def _msk_today() -> date:
    return datetime.now(tz=MSK).date()


def _msk_day_range_utc_naive(day_msk: date) -> tuple[datetime, datetime]:
    start_msk = datetime(day_msk.year, day_msk.month, day_msk.day, 0, 0, 0, tzinfo=MSK)
    end_msk = start_msk + timedelta(days=1)
    start_utc = start_msk.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_msk.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def pick_participant_of_day(chat_id: int, picked_by_tg_id: int | None = None) -> PickResult:
    _ensure_table()
    today = _msk_today()
    yesterday = today - timedelta(days=1)

    session = SessionLocal()
    try:
        existing = (
            session.query(DailyPick)
            .filter(
                DailyPick.chat_id == chat_id,
                DailyPick.day_msk == today,
                DailyPick.title == TITLE_PARTICIPANT_OF_DAY,
            )
            .first()
        )
        if existing:
            user = session.query(User).filter(User.tg_id == existing.winner_tg_id).first()
            return PickResult(
                day_msk=today,
                candidates_day_msk=yesterday,
                winner_tg_id=int(existing.winner_tg_id),
                winner_username=user.username if user else None,
                winner_fullname=user.fullname if user else None,
                is_new=False,
            )

        start_utc, end_utc = _msk_day_range_utc_naive(yesterday)
        rows = (
            session.query(distinct(User.tg_id))
            .join(Message, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= start_utc,
                Message.created_at < end_utc,
            )
            .all()
        )
        candidates = [int(tg_id) for (tg_id,) in rows if tg_id is not None]
        if not candidates:
            raise RuntimeError("Нет кандидатов: вчера в этом чате не было сообщений.")

        winner_tg_id = secrets.choice(candidates)
        record = DailyPick(
            chat_id=chat_id,
            day_msk=today,
            winner_tg_id=winner_tg_id,
            title=TITLE_PARTICIPANT_OF_DAY,
            picked_by_tg_id=picked_by_tg_id,
        )
        session.add(record)
        session.commit()

        user = session.query(User).filter(User.tg_id == winner_tg_id).first()
        return PickResult(
            day_msk=today,
            candidates_day_msk=yesterday,
            winner_tg_id=winner_tg_id,
            winner_username=user.username if user else None,
            winner_fullname=user.fullname if user else None,
            is_new=True,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
