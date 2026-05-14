"""Импорт и авто-резолюция рынков из polymarket.com и manifold.markets.

Поддерживается:
- Бинарные рынки (Yes/No) — Polymarket
- Бинарные (BINARY) и multi-choice (MULTIPLE_CHOICE) — Manifold

Архитектура:
- `parse_url(url)` → (source, slug|id) | None
- `fetch_external_market(url)` → ExternalMarketData
- `import_market(chat_id, creator_user_id, url)` → создаёт internal market с type=source
- `auto_resolve_external()` — для scheduler: проверяет статус всех импортированных open/closed рынков
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from sqlalchemy import or_

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.market import Market, MarketOption
from services.markets_service import (
    InvalidArgument,
    MarketError,
    MARKET_CREATION_FEE,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
    resolve_market,
)

logger = get_logger(__name__)

EXTERNAL_CHECK_TIMEOUT_SEC = float(os.getenv("EXTERNAL_MARKETS_HTTP_TIMEOUT", "30"))
EXTERNAL_IMPORT_FEE = int(os.getenv("MARKET_IMPORT_FEE", "50"))  # дешевле обычного create

POLYMARKET_RE = re.compile(r"polymarket\.com/(?:event|market)/([\w-]+)")
MANIFOLD_RE = re.compile(r"manifold\.markets/[\w_.\-]+/([\w-]+)")


@dataclass
class ExternalMarketData:
    source: str
    external_id: str
    external_url: str
    question: str
    options: list[str]
    close_time: datetime
    is_resolved: bool
    resolution: str | None  # лейбл победившей опции, если resolved


def parse_url(url: str) -> tuple[str, str] | None:
    if not url:
        return None
    m = POLYMARKET_RE.search(url)
    if m:
        return ("polymarket", m.group(1))
    m = MANIFOLD_RE.search(url)
    if m:
        return ("manifold", m.group(1))
    return None


async def _http_get_json(url: str) -> dict | list:
    timeout = aiohttp.ClientTimeout(total=EXTERNAL_CHECK_TIMEOUT_SEC)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "xyloz-tg-bot/1.0", "Accept": "application/json"},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    # 2026-05-14T12:00:00.000Z → datetime UTC naive
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


# ---------------- Polymarket ----------------


async def _fetch_polymarket(slug: str) -> ExternalMarketData:
    """Поддерживаем только /market/<slug> (одиночный Yes/No).
    Если URL ведёт на /event/<slug> (event-категория с под-рынками) —
    говорим пользователю дать ссылку на конкретный под-рынок: parimutuel
    с одним победителем плохо мапится на 33 независимых Yes/No вопроса.
    """
    body = await _http_get_json(
        f"https://gamma-api.polymarket.com/markets?slug={slug}&limit=1"
    )
    items = body if isinstance(body, list) else [body] if body else []
    if items:
        return _build_single_market(items[0], slug)

    # Не нашли как market — может это event? Диагностика.
    body = await _http_get_json(
        f"https://gamma-api.polymarket.com/events?slug={slug}"
    )
    events = body if isinstance(body, list) else [body] if body else []
    if events:
        ev = events[0]
        n_subs = len(ev.get("markets") or [])
        raise InvalidArgument(
            f"Polymarket: '{slug}' — это event-категория ({n_subs} под-рынков), а не отдельный рынок. "
            f"Открой нужный под-рынок на polymarket.com и скопируй URL вида polymarket.com/market/<slug>."
        )

    raise InvalidArgument(f"Polymarket: рынок '{slug}' не найден")


def _build_single_market(m: dict, slug: str) -> ExternalMarketData:
    raw_outcomes = m.get("outcomes") or '["Yes","No"]'
    if isinstance(raw_outcomes, str):
        try:
            outcomes = json.loads(raw_outcomes)
        except json.JSONDecodeError:
            outcomes = ["Yes", "No"]
    else:
        outcomes = list(raw_outcomes)

    raw_prices = m.get("outcomePrices") or "[]"
    if isinstance(raw_prices, str):
        try:
            prices = json.loads(raw_prices)
        except json.JSONDecodeError:
            prices = []
    else:
        prices = list(raw_prices)
    prices = [float(p) for p in prices]

    is_resolved = bool(m.get("closed") or m.get("isResolved"))
    resolution = None
    if is_resolved and prices and len(prices) == len(outcomes):
        resolution = outcomes[prices.index(max(prices))]

    close_time = _parse_iso(m.get("endDate") or m.get("closeTime")) or (
        datetime.utcnow() + timedelta(days=30)
    )
    return ExternalMarketData(
        source="polymarket",
        external_id=str(m.get("id") or m.get("conditionId") or slug),
        external_url=f"https://polymarket.com/market/{slug}",
        question=m.get("question") or m.get("title") or "(no question)",
        options=outcomes,
        close_time=close_time,
        is_resolved=is_resolved,
        resolution=resolution,
    )


# ---------------- Manifold ----------------


async def _fetch_manifold(slug: str) -> ExternalMarketData:
    url = f"https://api.manifold.markets/v0/slug/{slug}"
    m = await _http_get_json(url)
    if not isinstance(m, dict) or not m.get("id"):
        raise InvalidArgument(f"Manifold: рынок '{slug}' не найден")

    outcome_type = m.get("outcomeType") or "BINARY"
    is_resolved = bool(m.get("isResolved"))
    raw_resolution = m.get("resolution")  # 'YES'/'NO'/'MKT'/'CANCEL' для BINARY; option id для MC

    if outcome_type == "BINARY":
        options = ["Yes", "No"]
        if is_resolved and raw_resolution in ("YES", "NO"):
            resolution = "Yes" if raw_resolution == "YES" else "No"
        else:
            resolution = None
    elif outcome_type == "MULTIPLE_CHOICE":
        answers = m.get("answers") or []
        options = [str(a.get("text", "?"))[:100] for a in answers[:6]]
        resolution = None
        if is_resolved and raw_resolution:
            for a in answers:
                if a.get("id") == raw_resolution:
                    resolution = str(a.get("text", "?"))[:100]
                    break
    else:
        raise InvalidArgument(f"Manifold: тип '{outcome_type}' не поддерживается (только BINARY и MULTIPLE_CHOICE)")

    close_ms = m.get("closeTime")
    if close_ms:
        close_time = datetime.utcfromtimestamp(close_ms / 1000)
    else:
        close_time = datetime.utcnow() + timedelta(days=30)

    return ExternalMarketData(
        source="manifold",
        external_id=str(m["id"]),
        external_url=m.get("url") or f"https://manifold.markets/_/{slug}",
        question=m.get("question") or "(no question)",
        options=options,
        close_time=close_time,
        is_resolved=is_resolved,
        resolution=resolution,
    )


# ---------------- main API ----------------


async def fetch_external_market(url: str) -> ExternalMarketData:
    parsed = parse_url(url)
    if not parsed:
        raise InvalidArgument("URL не похож на polymarket.com или manifold.markets")
    source, identifier = parsed
    if source == "polymarket":
        return await _fetch_polymarket(identifier)
    return await _fetch_manifold(identifier)


def _create_imported_market_sync(
    chat_id: int,
    creator_user_id: int,
    data: ExternalMarketData,
) -> dict:
    if len(data.options) < 2:
        raise InvalidArgument("Внешний рынок должен иметь как минимум 2 опции")
    session = SessionLocal()
    try:
        creator_balance = _get_or_create_balance(session, creator_user_id, chat_id)
        if creator_balance.balance < EXTERNAL_IMPORT_FEE:
            raise InvalidArgument(
                f"Не хватает на комиссию импорта: нужно {EXTERNAL_IMPORT_FEE}, у тебя {creator_balance.balance}"
            )
        creator_balance.balance -= EXTERNAL_IMPORT_FEE
        creator_balance.updated_at = datetime.utcnow()
        bank = _get_or_create_bank(session, chat_id)
        bank.balance += EXTERNAL_IMPORT_FEE
        bank.updated_at = datetime.utcnow()

        # Не создаём дубль если уже импортировали тот же external_id
        existing = (
            session.query(Market)
            .filter(
                Market.chat_id == chat_id,
                Market.type == data.source,
                Market.external_id == data.external_id,
            )
            .first()
        )
        if existing:
            session.rollback()
            return {"market_id": existing.id, "already_imported": True}

        market = Market(
            chat_id=chat_id,
            type=data.source,
            question=data.question,
            creator_id=creator_user_id,
            status="open" if not data.is_resolved else "closed",
            closes_at=data.close_time,
            external_url=data.external_url,
            external_id=data.external_id,
        )
        session.add(market)
        session.flush()

        option_ids = []
        for idx, label in enumerate(data.options):
            opt = MarketOption(market_id=market.id, label=label[:200], position=idx)
            session.add(opt)
            session.flush()
            option_ids.append(opt.id)

        _log_tx(session, creator_user_id, chat_id, -EXTERNAL_IMPORT_FEE,
                kind="market_import_fee_user", ref_id=str(market.id),
                note=f"import {data.source} #{market.id}")
        _log_tx(session, None, chat_id, EXTERNAL_IMPORT_FEE,
                kind="market_import_fee_bank", ref_id=str(market.id))

        session.commit()
        return {
            "market_id": market.id,
            "already_imported": False,
            "source": data.source,
            "question": data.question,
            "options": data.options,
            "closes_at": data.close_time,
            "is_resolved": data.is_resolved,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def import_market(chat_id: int, creator_user_id: int, url: str) -> dict:
    data = await fetch_external_market(url)
    return await asyncio.to_thread(_create_imported_market_sync, chat_id, creator_user_id, data)


# ---------------- auto-resolve ----------------


def _winning_option_position(options: list[MarketOption], resolution_label: str) -> int | None:
    if not resolution_label:
        return None
    target = resolution_label.lower().strip()
    for i, opt in enumerate(options, 1):
        if opt.label.lower().strip() == target:
            return i
    return None


def _list_pending_external() -> list[Market]:
    session = SessionLocal()
    try:
        return (
            session.query(Market)
            .filter(
                Market.type.in_(["polymarket", "manifold"]),
                Market.status.in_(["open", "closed"]),
            )
            .order_by(Market.created_at.asc())
            .all()
        )
    finally:
        session.close()


def _options_for(market_id: int) -> list[MarketOption]:
    session = SessionLocal()
    try:
        return (
            session.query(MarketOption)
            .filter(MarketOption.market_id == market_id)
            .order_by(MarketOption.position.asc())
            .all()
        )
    finally:
        session.close()


async def auto_resolve_external() -> dict:
    """Возвращает статистику {checked, resolved, errors}. Вызывается из scheduler."""
    pending = await asyncio.to_thread(_list_pending_external)
    stats = {"checked": 0, "resolved": 0, "errors": 0}
    for m in pending:
        if not m.external_url:
            continue
        stats["checked"] += 1
        try:
            data = await fetch_external_market(m.external_url)
        except Exception:
            logger.exception("external_check: fetch failed for market #%s (%s)", m.id, m.external_url)
            stats["errors"] += 1
            continue
        if not data.is_resolved or not data.resolution:
            continue
        options = await asyncio.to_thread(_options_for, m.id)
        pos = _winning_option_position(options, data.resolution)
        if pos is None:
            logger.warning(
                "external_check: cannot match resolution '%s' to options %s for market #%s",
                data.resolution, [o.label for o in options], m.id,
            )
            continue
        try:
            await asyncio.to_thread(resolve_market, m.id, pos)
            stats["resolved"] += 1
            logger.info("external_check: auto-resolved market #%s as '%s'", m.id, data.resolution)
        except Exception:
            logger.exception("external_check: failed to resolve market #%s", m.id)
            stats["errors"] += 1
    logger.info("external_check done: %s", stats)
    return stats
