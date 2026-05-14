"""Фраза дня — короткая абсурдная фраза в стиле чата. Кэш per-chat per-day."""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import func

from common import prompts
from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting
from common.models.message import Message
from services import ai_client
from services.summary_service import get_summary_model

logger = get_logger(__name__)

CONTEXT_HOURS = 24
CONTEXT_LIMIT = 80
MIN_MSG_LEN = 15
MIN_CONTEXT_LINES = 10


def _today_key(chat_id: int) -> str:
    return f"phrase:{chat_id}:{datetime.utcnow().date().isoformat()}"


def _ensure_table():
    BotSetting.__table__.create(bind=engine, checkfirst=True)


def _get_cached(key: str) -> str | None:
    _ensure_table()
    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == key).first()
        if row and row.value and row.value.strip():
            return row.value.strip()
        return None
    finally:
        session.close()


def _set_cached(key: str, value: str):
    _ensure_table()
    session = SessionLocal()
    try:
        row = session.query(BotSetting).filter(BotSetting.key == key).first()
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            session.add(BotSetting(key=key, value=value, updated_at=datetime.utcnow()))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _collect_context(chat_id: int) -> str | None:
    since = datetime.utcnow() - timedelta(hours=CONTEXT_HOURS)
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.text)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= since,
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= MIN_MSG_LEN,
            )
            .order_by(Message.created_at.desc())
            .limit(CONTEXT_LIMIT)
            .all()
        )
        lines = []
        for r in rows:
            t = (r[0] or "").strip().replace("\n", " ")
            if len(t) > 200:
                t = t[:200] + "…"
            lines.append(f"- {t}")
        if len(lines) < MIN_CONTEXT_LINES:
            return None
        return "\n".join(lines)
    finally:
        session.close()


async def get_phrase_of_day(chat_id: int, force: bool = False) -> str:
    key = _today_key(chat_id)
    if not force:
        cached = await asyncio.to_thread(_get_cached, key)
        if cached:
            return cached

    context = await asyncio.to_thread(_collect_context, chat_id)
    if context is None:
        return "За последние сутки в чате недостаточно активности для фразы дня."

    task = prompts.load("phrase_task").format(context=context)
    raw = await asyncio.to_thread(
        ai_client.call,
        task,
        get_summary_model(),
        prompts.load("phrase_system"),
    )
    # Берём первую непустую строку, чистим обёртки.
    phrase = ""
    for line in raw.splitlines():
        line = line.strip().strip('"«»\'`').strip()
        if line:
            phrase = line
            break
    if not phrase:
        return "Не получилось — попробуй ещё раз позже."
    await asyncio.to_thread(_set_cached, key, phrase)
    return phrase
