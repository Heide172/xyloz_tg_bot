"""Обратная связь из Mini App: баг-репорт / пожелание."""
import asyncio
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth
from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.feedback import Feedback

logger = get_logger(__name__)
router = APIRouter()


class FeedbackReq(BaseModel):
    kind: str = Field(pattern="^(bug|idea)$")
    text: str = Field(min_length=5, max_length=2000)


def _admin_tg_ids() -> list[int]:
    out = []
    for part in (os.getenv("BOT_ADMIN_IDS") or "").split(","):
        p = part.strip()
        if p:
            try:
                out.append(int(p))
            except ValueError:
                pass
    return out


def _save_and_notify(user_id: int, chat_id, kind: str, text: str, who: str) -> None:
    session = SessionLocal()
    try:
        fb = Feedback(
            user_id=user_id, chat_id=chat_id, kind=kind, text=text,
            status="new", created_at=datetime.utcnow(),
        )
        session.add(fb)
        session.commit()
        fid = fb.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    # Уведомить админов в ЛС
    from services.social_service import send_chat_message

    icon = "🐞 Баг" if kind == "bug" else "💡 Идея"
    note = f"{icon} #{fid} от {who}:\n\n{text}"
    for admin_id in _admin_tg_ids():
        try:
            send_chat_message(admin_id, note)
        except Exception:
            logger.warning("feedback notify failed for admin %s", admin_id)


@router.post("")
async def submit(req: FeedbackReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    user_id = ensure_db_user(auth)
    chat_id = auth.chat_id
    who = ("@" + auth.user.username) if auth.user.username else (
        auth.user.first_name or f"id{auth.user.id}"
    )
    try:
        await asyncio.to_thread(
            _save_and_notify, user_id, chat_id, req.kind, req.text.strip(), who
        )
    except Exception:
        logger.exception("feedback submit failed")
        raise HTTPException(status_code=500, detail="Не удалось сохранить")
    return {"ok": True}
