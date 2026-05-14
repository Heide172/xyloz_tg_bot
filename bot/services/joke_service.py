"""Анекдот дня. Кэш в BotSetting per UTC date."""
import asyncio
from datetime import datetime

from common import prompts
from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting
from services import ai_client
from services.summary_service import get_summary_model

logger = get_logger(__name__)


def _today_key() -> str:
    return f"joke:{datetime.utcnow().date().isoformat()}"


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


async def get_joke_of_day(force: bool = False) -> str:
    key = _today_key()
    if not force:
        cached = await asyncio.to_thread(_get_cached, key)
        if cached:
            return cached

    text = await asyncio.to_thread(
        ai_client.call,
        prompts.load("joke_task"),
        get_summary_model(),
        prompts.load("joke_system"),
    )
    text = text.strip().strip('"«»\'')
    if not text:
        return "Не получилось — попробуй ещё раз позже."
    await asyncio.to_thread(_set_cached, key, text)
    return text
