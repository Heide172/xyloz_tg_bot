"""Usage-аналитика Mini App: запись событий + сводка для админа.

Best-effort запись: ошибка не должна ронять основной запрос.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.app_event import AppEvent

logger = get_logger(__name__)

_ALLOWED = {"view", "action"}
_PROPS_MAX = 1000


def record_event(user_id: int | None, chat_id: int | None,
                 event: str, props: dict | None) -> None:
    event = (event or "").strip()[:48]
    if event not in _ALLOWED:
        return
    p = props if isinstance(props, dict) else {}
    # обрезаем разрастание: только строковые/числовые значения, ≤_PROPS_MAX
    clean = {}
    for k, v in list(p.items())[:20]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            clean[str(k)[:40]] = (v[:200] if isinstance(v, str) else v)
    session = SessionLocal()
    try:
        session.add(AppEvent(
            user_id=user_id, chat_id=chat_id, event=event,
            props=clean, ts=datetime.utcnow(),
        ))
        session.commit()
    except Exception:
        session.rollback()
        logger.debug("record_event failed")
    finally:
        session.close()


def summary(hours: int = 24, top: int = 30) -> dict:
    """Сводка за последние `hours` ч: всего, уникальные юзеры,
    топ view-роутов и action-имён."""
    since = datetime.utcnow() - timedelta(hours=hours)
    session = SessionLocal()
    try:
        total = (
            session.query(func.count(AppEvent.id))
            .filter(AppEvent.ts >= since).scalar() or 0
        )
        uniq = (
            session.query(func.count(func.distinct(AppEvent.user_id)))
            .filter(AppEvent.ts >= since).scalar() or 0
        )

        def _top(ev: str, key: str):
            col = AppEvent.props[key].astext
            rows = (
                session.query(col, func.count(AppEvent.id))
                .filter(AppEvent.ts >= since, AppEvent.event == ev,
                        col.isnot(None))
                .group_by(col)
                .order_by(func.count(AppEvent.id).desc())
                .limit(top)
                .all()
            )
            return [{"name": r[0], "n": int(r[1])} for r in rows]

        return {
            "hours": hours,
            "total": int(total),
            "unique_users": int(uniq),
            "views": _top("view", "route"),
            "actions": _top("action", "name"),
        }
    except Exception as exc:
        logger.warning("analytics summary failed: %s", str(exc)[:120])
        return {"hours": hours, "total": 0, "unique_users": 0,
                "views": [], "actions": []}
    finally:
        session.close()
