"""Гача-ферма API: крутка, коллекция, выбор героини, баннер (admin)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import (
    TgWebAppAuth,
    ensure_db_user,
    is_admin,
    require_auth,
    require_chat_membership,
)
from services.gacha_service import (
    InsufficientFunds,
    InvalidArgument,
    buy_gems_sync,
    collection_sync,
    daily_sync,
    pet_sync,
    roll_sync,
    set_banner,
    set_heroine_sync,
)
from services.pvp_service import (
    arena_fight_sync,
    auto_team_sync,
    ladder_sync,
    matchmake_cancel_sync,
    matchmake_join_sync,
)
from services.payments_service import (
    STARS_TO_HRYVNIA,
    create_stars_invoice_link,
)

router = APIRouter()


class RollReq(BaseModel):
    count: int = Field(default=1)


class HeroineReq(BaseModel):
    char_id: str


class PetReq(BaseModel):
    char_id: str


class BannerReq(BaseModel):
    char_id: str


class StarsInvoiceReq(BaseModel):
    stars: int = Field(ge=1, le=2500, description="кол-во звёзд (1..2500)")


class BuyGemsReq(BaseModel):
    gems: int = Field(ge=1, le=10000, description="сколько gems купить за cp")


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (InvalidArgument, InsufficientFunds)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.get("/collection")
async def collection(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(collection_sync, user_id, chat_id)


@router.post("/roll")
async def roll(req: RollReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(roll_sync, user_id, chat_id, req.count)
    except Exception as e:
        raise _err(e)


@router.post("/heroine")
async def heroine(req: HeroineReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(set_heroine_sync, user_id, chat_id, req.char_id)
    except Exception as e:
        raise _err(e)


@router.post("/daily")
async def daily(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Забрать ежедневный бонус (раз в сутки)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(daily_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)


@router.post("/pet")
async def pet(req: PetReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """«Приласкать» персонажа: +привязанность, случайная фраза."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(pet_sync, user_id, chat_id, req.char_id)
    except Exception as e:
        raise _err(e)


# ---------------- v2: gems + PvP ----------------


@router.post("/gems/buy")
async def gems_buy(req: BuyGemsReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Купить gems за cp фермы (курс CP_PER_GEM)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(buy_gems_sync, user_id, chat_id, req.gems)
    except Exception as e:
        raise _err(e)


@router.get("/team")
async def team(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Авто-команда (топ-5 карт по силе) — превью состава."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(auto_team_sync, user_id, chat_id)


@router.post("/arena")
async def arena(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Бой на арене против бот-команды (мгновенно)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(arena_fight_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)


@router.post("/pvp/queue")
async def pvp_queue(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Встать в очередь матчмейка (мгновенный бой, если есть оппонент)."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        return await asyncio.to_thread(matchmake_join_sync, user_id, chat_id)
    except Exception as e:
        raise _err(e)


@router.post("/pvp/cancel")
async def pvp_cancel(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    return await asyncio.to_thread(matchmake_cancel_sync, user_id, chat_id)


@router.get("/pvp/ladder")
async def pvp_ladder(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    return await asyncio.to_thread(ladder_sync, chat_id)


@router.post("/banner")
async def banner(req: BannerReq, auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    await require_chat_membership(auth)
    if not is_admin(auth.user.id):
        raise HTTPException(status_code=403, detail="Только для админов бота")
    try:
        await asyncio.to_thread(set_banner, req.char_id)
        return {"banner": req.char_id}
    except Exception as e:
        raise _err(e)


@router.post("/stars_invoice")
async def stars_invoice(
    req: StarsInvoiceReq, auth: TgWebAppAuth = Depends(require_auth)
) -> dict:
    """Создать Stars-invoice для покупки гривен. Возвращает URL для openInvoice."""
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        url = await asyncio.to_thread(
            create_stars_invoice_link, user_id, chat_id, req.stars, "gacha"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Telegram отказал: {exc}")
    return {
        "url": url,
        "stars": req.stars,
        "hryvnia": req.stars * STARS_TO_HRYVNIA,
        "rate": STARS_TO_HRYVNIA,
    }
