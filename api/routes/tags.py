"""Рынок аренды кастомных Telegram-тегов."""
import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from common.db.db import SessionLocal
from common.models.user import User
from services.economy_service import resolve_user_by_username
from services.markets_service import InsufficientFunds, InvalidArgument
from services.tag_rental_service import (
    cancel_sync,
    quote,
    reapply_sync,
    rent_sync,
    state_sync,
)

router = APIRouter()


class RentReq(BaseModel):
    title: str = Field(min_length=1, max_length=16)
    days: int = Field(ge=1, le=7)
    gift_to: str | None = Field(
        default=None, description="@username или tg_id — подарить тег другому"
    )


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


def _resolve_gift_recipient(target: str) -> tuple[int, int]:
    """Возвращает (db_user_id, tg_user_id) или кидает 4xx."""
    target = target.strip()
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", target)
    if m:
        u = resolve_user_by_username(m.group(1))
        if u is None:
            raise HTTPException(status_code=404, detail=f"Юзер {target} не найден")
        return u.id, u.tg_id
    try:
        tg_id = int(target)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Получатель: @username или tg_id"
        )
    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == tg_id).first()
        if u is None:
            raise HTTPException(status_code=404, detail=f"tg_id {tg_id} не найден")
        return u.id, u.tg_id
    finally:
        session.close()


@router.get("/state")
async def state(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(state_sync, user_id, chat_id)


@router.get("/quote")
async def quote_route(days: int, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    try:
        return {"days": days, "price": quote(days)}
    except Exception as e:
        raise _err(e)


@router.post("/rent")
async def rent(req: RentReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    payer_user_id = ensure_db_user(auth)
    recipient_user_id = None
    recipient_tg_id = None
    if req.gift_to:
        recipient_user_id, recipient_tg_id = _resolve_gift_recipient(req.gift_to)
        if recipient_user_id == payer_user_id:
            raise HTTPException(
                status_code=400, detail="Самому себе подарок не нужен — просто купи."
            )
    try:
        result = await asyncio.to_thread(
            rent_sync,
            payer_user_id,
            auth.user.id,
            chat_id,
            req.title,
            req.days,
            recipient_user_id,
            recipient_tg_id,
        )
    except Exception as e:
        raise _err(e)
    # Уведомление получателю подарка (best effort)
    if result.get("gift") and recipient_tg_id:
        try:
            from services.social_service import send_chat_message

            sender = (
                "@" + auth.user.username
                if auth.user.username
                else (auth.user.first_name or f"id{auth.user.id}")
            )
            note = (
                f"🎁 {sender} подарил(а) тебе тег «{result['title']}» "
                f"на {req.days} дн."
            )
            if not result.get("tg_applied"):
                note += (
                    f"\n\n⚠️ Telegram отказал в установке тега: "
                    f"{result.get('tg_error') or 'неизвестная ошибка'}"
                )
            await asyncio.to_thread(send_chat_message, recipient_tg_id, note)
        except Exception:
            pass
    return result


@router.post("/cancel")
async def cancel(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(cancel_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)


@router.post("/reapply")
async def reapply(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Повторно выставить тег если предыдущий TG-вызов провалился."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(reapply_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)
