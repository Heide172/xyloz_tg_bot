"""Работа с БД: session_scope + идемпотентный upsert + выборки. Поверх common.db."""
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.db.db import SessionLocal
from common.models import VpnMessage, VpnMonitoredChat


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def store_messages(rows: list[dict]) -> int:
    """Bulk upsert. ON CONFLICT (chat_id, telegram_message_id) -> обновить text/edited."""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    with session_scope() as s:
        stmt = pg_insert(VpnMessage).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["chat_id", "telegram_message_id"],
            set_={
                "text": stmt.excluded.text,
                "edited_at": stmt.excluded.edited_at,
                "has_media": stmt.excluded.has_media,
                "topic_title": stmt.excluded.topic_title,
            },
        )
        s.execute(stmt)
    return len(rows)


def register_chat(chat) -> None:
    """Зарегистрировать/обновить monitored-чат (id, title, is_forum)."""
    with session_scope() as s:
        stmt = pg_insert(VpnMonitoredChat).values(
            id=chat.id,
            title=getattr(chat, "title", None) or getattr(chat, "first_name", None),
            username=getattr(chat, "username", None),
            is_forum=bool(getattr(chat, "is_forum", False)),
            enabled=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"title": stmt.excluded.title, "is_forum": stmt.excluded.is_forum},
        )
        s.execute(stmt)


def fetch_window(start: datetime, end: datetime) -> list[VpnMessage]:
    """Все сообщения с created_at в [start, end)."""
    with session_scope() as s:
        rows = s.scalars(
            select(VpnMessage)
            .where(VpnMessage.created_at >= start, VpnMessage.created_at < end)
            .order_by(VpnMessage.chat_id, VpnMessage.topic_id, VpnMessage.created_at)
        ).all()
        s.expunge_all()
        return list(rows)


def chat_titles() -> dict[int, str]:
    with session_scope() as s:
        rows = s.scalars(select(VpnMonitoredChat)).all()
        return {c.id: (c.title or c.username or str(c.id)) for c in rows}
