"""API мини-игр: coinflip, dice, slots, roulette, blackjack."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from services.casino_service import (
    CasinoError,
    GameNotFound,
    GameNotActive,
    InvalidArgument,
    InsufficientFunds,
    GameResult,
    double_blackjack_sync,
    hit_blackjack_sync,
    play_coinflip_sync,
    play_dice_sync,
    play_roulette_sync,
    play_slots_sync,
    stand_blackjack_sync,
    start_blackjack_sync,
)

router = APIRouter()


class CoinflipReq(BaseModel):
    bet: int = Field(ge=1)
    pick: str  # heads | tails


class DiceReq(BaseModel):
    bet: int = Field(ge=1)
    mode: str  # over | under
    threshold: int = Field(ge=1, le=99)


class SlotsReq(BaseModel):
    bet: int = Field(ge=1)


class RouletteReq(BaseModel):
    bet: int = Field(ge=1)
    bet_type: str           # number | color | parity | half | dozen
    value: str | None = None


class BlackjackStartReq(BaseModel):
    bet: int = Field(ge=1)


class GameResp(BaseModel):
    game_id: int
    game: str
    outcome: str
    bet: int
    payout: int
    net: int
    user_balance_after: int
    bank_after: int
    details: dict


def _to_resp(r: GameResult) -> GameResp:
    return GameResp(
        game_id=r.game_id,
        game=r.game,
        outcome=r.outcome,
        bet=r.bet,
        payout=r.payout,
        net=r.net,
        user_balance_after=r.user_balance_after,
        bank_after=r.bank_after,
        details=r.details,
    )


def _map_error(e: Exception) -> HTTPException:
    if isinstance(e, InvalidArgument):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, InsufficientFunds):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, GameNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, GameNotActive):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, CasinoError):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail="internal error")


@router.post("/coinflip", response_model=GameResp)
async def coinflip(req: CoinflipReq, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(play_coinflip_sync, chat_id, user_id, req.bet, req.pick)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/dice", response_model=GameResp)
async def dice(req: DiceReq, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(play_dice_sync, chat_id, user_id, req.bet, req.mode, req.threshold)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/slots", response_model=GameResp)
async def slots(req: SlotsReq, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(play_slots_sync, chat_id, user_id, req.bet)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/roulette", response_model=GameResp)
async def roulette(req: RouletteReq, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(
            play_roulette_sync, chat_id, user_id, req.bet, req.bet_type, req.value
        )
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/blackjack/start", response_model=GameResp)
async def blackjack_start(
    req: BlackjackStartReq, auth: TgWebAppAuth = Depends(require_auth)
) -> GameResp:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(start_blackjack_sync, chat_id, user_id, req.bet)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/blackjack/{game_id}/hit", response_model=GameResp)
async def blackjack_hit(game_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(hit_blackjack_sync, game_id, user_id)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/blackjack/{game_id}/stand", response_model=GameResp)
async def blackjack_stand(game_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(stand_blackjack_sync, game_id, user_id)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)


@router.post("/blackjack/{game_id}/double", response_model=GameResp)
async def blackjack_double(game_id: int, auth: TgWebAppAuth = Depends(require_auth)) -> GameResp:
    await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        r = await asyncio.to_thread(double_blackjack_sync, game_id, user_id)
        return _to_resp(r)
    except Exception as e:
        raise _map_error(e)
