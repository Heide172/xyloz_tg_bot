"""Обратная связь из Mini App: ИИ-форма (основная) + ручная (фолбэк)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth
from common.logger.logger import get_logger
from services.feedback_ai_service import assist
from services.feedback_service import (
    create_feedback,
    default_reward,
    list_by_user,
)

logger = get_logger(__name__)
router = APIRouter()


def _who(auth: TgWebAppAuth) -> str:
    return ("@" + auth.user.username) if auth.user.username else (
        auth.user.first_name or f"id{auth.user.id}"
    )


class FeedbackReq(BaseModel):
    kind: str = Field(pattern="^(bug|idea)$")
    text: str = Field(min_length=5, max_length=2000)


class AssistReq(BaseModel):
    message: str = Field(min_length=2, max_length=2000)


@router.post("")
async def submit(req: FeedbackReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Ручная отправка (фолбэк, без ИИ)."""
    user_id = ensure_db_user(auth)
    try:
        await asyncio.to_thread(
            create_feedback, user_id, auth.chat_id, req.kind,
            req.text.strip(), _who(auth),
        )
    except Exception:
        logger.exception("feedback submit failed")
        raise HTTPException(status_code=500, detail="Не удалось сохранить")
    return {"ok": True}


@router.post("/assist")
async def assist_route(
    req: AssistReq, auth: TgWebAppAuth = Depends(require_auth)
) -> dict:
    """ИИ-форма: отвечает и при необходимости сам заводит заявку."""
    user_id = ensure_db_user(auth)
    try:
        res = await asyncio.to_thread(
            assist, user_id, auth.chat_id, _who(auth), req.message
        )
    except Exception:
        logger.exception("feedback assist failed")
        raise HTTPException(status_code=500, detail="ИИ недоступен")
    return res


@router.get("/mine")
async def mine(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Все заявки текущего юзера — со статусом и наградой."""
    user_id = ensure_db_user(auth)
    rows = await asyncio.to_thread(list_by_user, user_id, 50)
    return {
        "items": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "text": r["text"],
                "reward": r["reward"],
                "default_reward": default_reward(r["kind"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "rewarded_at": (
                    r["rewarded_at"].isoformat() if r["rewarded_at"] else None
                ),
            }
            for r in rows
        ]
    }
