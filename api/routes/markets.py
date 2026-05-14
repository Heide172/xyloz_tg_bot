from fastapi import APIRouter, Depends, HTTPException, Path, Query

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from api.schemas import (
    CreateMarketRequest,
    CreateMarketResponse,
    ImportMarketRequest,
    ImportMarketResponse,
    MarketPublic,
    MarketsList,
    PlaceBetRequest,
    PlaceBetResponse,
)
from api.serializers import market_to_schema
from services.external_markets import import_market as svc_import_market
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    MarketClosed,
    MarketNotFound,
    create_market,
    get_market,
    list_markets,
    parse_duration,
    place_bet,
)

router = APIRouter()


def _market_or_404(market_id: int, chat_id: int):
    view = get_market(market_id)
    if view is None or view.market.chat_id != chat_id:
        raise HTTPException(status_code=404, detail=f"Market #{market_id} not found in this chat")
    return view


@router.get("", response_model=MarketsList)
async def list_markets_route(
    status: str | None = Query(default="open", description="open|closed|resolved|cancelled|all"),
    auth: TgWebAppAuth = Depends(require_auth),
) -> MarketsList:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    effective_status = None if (status in (None, "all")) else status
    views = list_markets(chat_id=chat_id, status=effective_status, limit=50)
    return MarketsList(
        items=[market_to_schema(v.market, v.options, v.bets_count) for v in views],
    )


@router.get("/{market_id}", response_model=MarketPublic)
async def market_detail(
    market_id: int = Path(..., ge=1),
    auth: TgWebAppAuth = Depends(require_auth),
) -> MarketPublic:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    view = _market_or_404(market_id, chat_id)
    return market_to_schema(view.market, view.options, view.bets_count)


@router.post("", response_model=CreateMarketResponse)
async def create_market_route(
    body: CreateMarketRequest,
    auth: TgWebAppAuth = Depends(require_auth),
) -> CreateMarketResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        duration = parse_duration(body.duration)
        result = create_market(
            chat_id=chat_id,
            creator_user_id=user_id,
            question=body.question,
            options=body.options,
            duration=duration,
        )
    except InsufficientFunds as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    view = get_market(result.market_id)
    return CreateMarketResponse(
        market=market_to_schema(view.market, view.options, view.bets_count),
        fee_charged=result.fee_charged,
    )


@router.post("/{market_id}/bets", response_model=PlaceBetResponse)
async def place_bet_route(
    body: PlaceBetRequest,
    market_id: int = Path(..., ge=1),
    auth: TgWebAppAuth = Depends(require_auth),
) -> PlaceBetResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    _market_or_404(market_id, chat_id)
    try:
        result = place_bet(
            market_id=market_id,
            option_position=body.option_position,
            user_id=user_id,
            amount=body.amount,
        )
    except MarketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MarketClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InsufficientFunds as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    return PlaceBetResponse(**result)


@router.post("/import", response_model=ImportMarketResponse)
async def import_market_route(
    body: ImportMarketRequest,
    auth: TgWebAppAuth = Depends(require_auth),
) -> ImportMarketResponse:
    chat_id = await require_chat_membership(auth)
    user_id = ensure_db_user(auth)
    try:
        result = await svc_import_market(chat_id=chat_id, creator_user_id=user_id, url=body.url)
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InsufficientFunds as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    view = get_market(result["market_id"])
    return ImportMarketResponse(
        market=market_to_schema(view.market, view.options, view.bets_count),
        already_imported=result.get("already_imported", False),
    )
