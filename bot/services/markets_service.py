"""Внутренние рынки на parimutuel-механике.

- Любой участник может создать рынок. Списывается фикс. комиссия в банк чата.
- Любой ставит на любую опцию (только для открытых рынков, до closes_at).
- При резолюции: 5% от общего пула в банк, остальное победителям пропорционально ставке.
- Если на победившую опцию никто не ставил — возвращаем все ставки (как cancel).

Все денежные операции идут через economy_tx (логирование) + user_balance / chat_bank.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_bank import ChatBank
from common.models.economy_tx import EconomyTx
from common.models.market import Bet, Market, MarketOption
from common.models.user import User
from common.models.user_balance import UserBalance

logger = get_logger(__name__)

MARKET_CREATION_FEE = int(os.getenv("MARKET_CREATION_FEE", "100"))
MARKET_RESOLUTION_FEE_PCT = float(os.getenv("MARKET_RESOLUTION_FEE_PCT", "5"))
MARKET_MIN_BET = int(os.getenv("MARKET_MIN_BET", "10"))
MARKET_MIN_OPTIONS = 2
MARKET_MAX_OPTIONS = 6
MARKET_MIN_QUESTION_LEN = 5
MARKET_MAX_QUESTION_LEN = 400
MARKET_MIN_OPTION_LEN = 1
MARKET_MAX_OPTION_LEN = 100
MARKET_MIN_DURATION_MIN = 5
MARKET_MAX_DURATION_DAYS = 365


# ---------------- exceptions ----------------


class MarketError(Exception):
    pass


class InsufficientFunds(MarketError):
    pass


class MarketNotFound(MarketError):
    pass


class MarketClosed(MarketError):
    pass


class InvalidArgument(MarketError):
    pass


# ---------------- helpers ----------------


def _get_or_create_balance(session, user_id: int, chat_id: int) -> UserBalance:
    row = (
        session.query(UserBalance)
        .filter(UserBalance.user_id == user_id, UserBalance.chat_id == chat_id)
        .with_for_update()
        .first()
    )
    if row:
        return row
    row = UserBalance(user_id=user_id, chat_id=chat_id, balance=0)
    session.add(row)
    session.flush()
    return row


def _get_or_create_bank(session, chat_id: int) -> ChatBank:
    row = session.query(ChatBank).filter(ChatBank.chat_id == chat_id).with_for_update().first()
    if row:
        return row
    row = ChatBank(chat_id=chat_id, balance=0)
    session.add(row)
    session.flush()
    return row


def _log_tx(session, user_id: int | None, chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None):
    session.add(EconomyTx(
        user_id=user_id,
        chat_id=chat_id,
        amount=amount,
        kind=kind,
        ref_id=ref_id,
        note=note,
    ))


def parse_duration(arg: str) -> timedelta:
    """Понимает '7d', '12h', '90m'."""
    arg = (arg or "").strip().lower()
    if not arg:
        raise InvalidArgument("Дедлайн не задан")
    if arg.endswith("d"):
        return timedelta(days=int(arg[:-1]))
    if arg.endswith("h"):
        return timedelta(hours=int(arg[:-1]))
    if arg.endswith("m"):
        return timedelta(minutes=int(arg[:-1]))
    raise InvalidArgument(f"Дедлайн '{arg}': используй 7d / 12h / 90m")


# ---------------- create market ----------------


@dataclass
class CreatedMarket:
    market_id: int
    fee_charged: int
    options: list[tuple[int, str]]  # (option_id, label)


def create_market(
    chat_id: int,
    creator_user_id: int,
    question: str,
    options: list[str],
    duration: timedelta,
) -> CreatedMarket:
    question = (question or "").strip()
    if not (MARKET_MIN_QUESTION_LEN <= len(question) <= MARKET_MAX_QUESTION_LEN):
        raise InvalidArgument(f"Длина вопроса должна быть {MARKET_MIN_QUESTION_LEN}..{MARKET_MAX_QUESTION_LEN} символов")

    opts: list[str] = []
    for o in options:
        s = (o or "").strip()
        if MARKET_MIN_OPTION_LEN <= len(s) <= MARKET_MAX_OPTION_LEN:
            opts.append(s)
    if not (MARKET_MIN_OPTIONS <= len(opts) <= MARKET_MAX_OPTIONS):
        raise InvalidArgument(f"Опций должно быть {MARKET_MIN_OPTIONS}..{MARKET_MAX_OPTIONS}")
    if len(set(opts)) != len(opts):
        raise InvalidArgument("Опции должны быть уникальные")

    if duration < timedelta(minutes=MARKET_MIN_DURATION_MIN):
        raise InvalidArgument(f"Минимальная длительность — {MARKET_MIN_DURATION_MIN} минут")
    if duration > timedelta(days=MARKET_MAX_DURATION_DAYS):
        raise InvalidArgument(f"Максимальная длительность — {MARKET_MAX_DURATION_DAYS} дней")

    closes_at = datetime.utcnow() + duration

    session = SessionLocal()
    try:
        # Списать комиссию с creator → в банк чата.
        creator_balance = _get_or_create_balance(session, creator_user_id, chat_id)
        if creator_balance.balance < MARKET_CREATION_FEE:
            raise InsufficientFunds(
                f"Не хватает на комиссию: нужно {MARKET_CREATION_FEE}, у тебя {creator_balance.balance}"
            )
        creator_balance.balance -= MARKET_CREATION_FEE
        creator_balance.updated_at = datetime.utcnow()
        bank = _get_or_create_bank(session, chat_id)
        bank.balance += MARKET_CREATION_FEE
        bank.updated_at = datetime.utcnow()

        market = Market(
            chat_id=chat_id,
            type="internal",
            question=question,
            creator_id=creator_user_id,
            status="open",
            closes_at=closes_at,
        )
        session.add(market)
        session.flush()  # market.id

        option_pairs: list[tuple[int, str]] = []
        for idx, label in enumerate(opts):
            opt = MarketOption(market_id=market.id, label=label, position=idx)
            session.add(opt)
            session.flush()
            option_pairs.append((opt.id, label))

        _log_tx(session, creator_user_id, chat_id, -MARKET_CREATION_FEE,
                kind="market_create_fee_user", ref_id=str(market.id),
                note=f"market #{market.id}: {question[:60]}")
        _log_tx(session, None, chat_id, MARKET_CREATION_FEE,
                kind="market_create_fee_bank", ref_id=str(market.id),
                note=f"market #{market.id}")

        session.commit()
        return CreatedMarket(market_id=market.id, fee_charged=MARKET_CREATION_FEE, options=option_pairs)
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------- place bet ----------------


def place_bet(market_id: int, option_position: int, user_id: int, amount: int) -> dict:
    if amount < MARKET_MIN_BET:
        raise InvalidArgument(f"Минимальная ставка: {MARKET_MIN_BET}")
    session = SessionLocal()
    try:
        market = (
            session.query(Market)
            .filter(Market.id == market_id)
            .with_for_update()
            .first()
        )
        if not market:
            raise MarketNotFound(f"Рынок #{market_id} не найден")
        if market.status != "open":
            raise MarketClosed(f"Рынок #{market_id} в статусе {market.status}")
        if market.closes_at <= datetime.utcnow():
            market.status = "closed"
            session.commit()
            raise MarketClosed("Рынок уже закрыт по времени")

        options = (
            session.query(MarketOption)
            .filter(MarketOption.market_id == market.id)
            .order_by(MarketOption.position.asc())
            .with_for_update()
            .all()
        )
        if option_position < 1 or option_position > len(options):
            raise InvalidArgument(f"Опция должна быть 1..{len(options)}")
        option = options[option_position - 1]

        bal = _get_or_create_balance(session, user_id, market.chat_id)
        if bal.balance < amount:
            raise InsufficientFunds(f"Баланс {bal.balance} < ставка {amount}")
        bal.balance -= amount
        bal.updated_at = datetime.utcnow()
        option.pool += amount

        bet = Bet(market_id=market.id, option_id=option.id, user_id=user_id, amount=amount)
        session.add(bet)
        session.flush()
        _log_tx(session, user_id, market.chat_id, -amount,
                kind="bet_place", ref_id=str(bet.id),
                note=f"market #{market.id} option '{option.label}'")

        session.commit()
        return {
            "bet_id": bet.id,
            "market_id": market.id,
            "option_label": option.label,
            "option_pool_after": option.pool,
            "user_balance_after": bal.balance,
        }
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------- resolve / cancel ----------------


def resolve_market(market_id: int, winning_option_position: int) -> dict:
    session = SessionLocal()
    try:
        market = session.query(Market).filter(Market.id == market_id).with_for_update().first()
        if not market:
            raise MarketNotFound(f"Рынок #{market_id} не найден")
        if market.status in ("resolved", "cancelled"):
            raise InvalidArgument(f"Рынок уже {market.status}")

        options = (
            session.query(MarketOption)
            .filter(MarketOption.market_id == market.id)
            .order_by(MarketOption.position.asc())
            .with_for_update()
            .all()
        )
        if winning_option_position < 1 or winning_option_position > len(options):
            raise InvalidArgument(f"Опция должна быть 1..{len(options)}")
        winning_option = options[winning_option_position - 1]

        total_pool = sum(o.pool for o in options)
        winner_pool = winning_option.pool

        bets = session.query(Bet).filter(Bet.market_id == market.id).with_for_update().all()

        result = {
            "market_id": market.id,
            "winning_label": winning_option.label,
            "total_pool": total_pool,
            "winner_pool": winner_pool,
            "commission": 0,
            "distributed": 0,
            "payouts": [],
            "refunded": False,
        }

        if total_pool == 0:
            # никто не ставил — просто закрываем как resolved
            market.status = "resolved"
            market.resolved_at = datetime.utcnow()
            market.winning_option_id = winning_option.id
            session.commit()
            return result

        if winner_pool == 0:
            # никто не выиграл — рефанд всем
            for bet in bets:
                if bet.user_id is None:
                    continue
                bal = _get_or_create_balance(session, bet.user_id, market.chat_id)
                bal.balance += bet.amount
                bal.updated_at = datetime.utcnow()
                bet.refunded = 1
                bet.payout = bet.amount
                _log_tx(session, bet.user_id, market.chat_id, bet.amount,
                        kind="bet_refund", ref_id=str(bet.id),
                        note=f"market #{market.id} no winners")
            market.status = "resolved"
            market.resolved_at = datetime.utcnow()
            market.winning_option_id = winning_option.id
            result["refunded"] = True
            session.commit()
            return result

        # Комиссия в банк
        commission = int(total_pool * MARKET_RESOLUTION_FEE_PCT / 100)
        distributable = total_pool - commission

        if commission > 0:
            bank = _get_or_create_bank(session, market.chat_id)
            bank.balance += commission
            bank.updated_at = datetime.utcnow()
            _log_tx(session, None, market.chat_id, commission,
                    kind="market_resolve_fee_bank", ref_id=str(market.id),
                    note=f"market #{market.id} commission {MARKET_RESOLUTION_FEE_PCT}%")

        # Раздать победителям пропорционально вкладу
        for bet in bets:
            if bet.option_id != winning_option.id:
                bet.payout = 0
                continue
            if bet.user_id is None:
                bet.payout = 0
                continue
            share = bet.amount / winner_pool
            payout = int(distributable * share)
            bet.payout = payout
            bal = _get_or_create_balance(session, bet.user_id, market.chat_id)
            bal.balance += payout
            bal.updated_at = datetime.utcnow()
            _log_tx(session, bet.user_id, market.chat_id, payout,
                    kind="bet_payout", ref_id=str(bet.id),
                    note=f"market #{market.id} won on '{winning_option.label}'")
            result["payouts"].append({
                "user_id": bet.user_id,
                "bet_amount": bet.amount,
                "payout": payout,
            })

        result["commission"] = commission
        result["distributed"] = distributable

        market.status = "resolved"
        market.resolved_at = datetime.utcnow()
        market.winning_option_id = winning_option.id
        session.commit()
        return result
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


def cancel_market(market_id: int) -> dict:
    session = SessionLocal()
    try:
        market = session.query(Market).filter(Market.id == market_id).with_for_update().first()
        if not market:
            raise MarketNotFound(f"Рынок #{market_id} не найден")
        if market.status in ("resolved", "cancelled"):
            raise InvalidArgument(f"Рынок уже {market.status}")
        bets = session.query(Bet).filter(Bet.market_id == market.id).with_for_update().all()
        refund_count = 0
        for bet in bets:
            if bet.user_id is None or bet.refunded:
                continue
            bal = _get_or_create_balance(session, bet.user_id, market.chat_id)
            bal.balance += bet.amount
            bal.updated_at = datetime.utcnow()
            bet.refunded = 1
            bet.payout = bet.amount
            _log_tx(session, bet.user_id, market.chat_id, bet.amount,
                    kind="bet_refund", ref_id=str(bet.id),
                    note=f"market #{market.id} cancelled")
            refund_count += 1
        market.status = "cancelled"
        market.resolved_at = datetime.utcnow()
        session.commit()
        return {"market_id": market.id, "refunded": refund_count}
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------- read ----------------


@dataclass
class MarketView:
    market: Market
    options: list[MarketOption]
    total_pool: int
    bets_count: int


def get_market(market_id: int) -> MarketView | None:
    session = SessionLocal()
    try:
        market = session.query(Market).filter(Market.id == market_id).first()
        if not market:
            return None
        options = (
            session.query(MarketOption)
            .filter(MarketOption.market_id == market.id)
            .order_by(MarketOption.position.asc())
            .all()
        )
        total = sum(o.pool for o in options)
        bets_count = session.query(func.count(Bet.id)).filter(Bet.market_id == market.id).scalar() or 0
        return MarketView(market=market, options=options, total_pool=int(total), bets_count=int(bets_count))
    finally:
        session.close()


def list_markets(chat_id: int, status: str | None = None, limit: int = 20) -> list[MarketView]:
    session = SessionLocal()
    try:
        q = session.query(Market).filter(Market.chat_id == chat_id)
        if status:
            q = q.filter(Market.status == status)
        markets = q.order_by(Market.created_at.desc()).limit(limit).all()
        result = []
        for m in markets:
            options = (
                session.query(MarketOption)
                .filter(MarketOption.market_id == m.id)
                .order_by(MarketOption.position.asc())
                .all()
            )
            total = sum(o.pool for o in options)
            bets_count = session.query(func.count(Bet.id)).filter(Bet.market_id == m.id).scalar() or 0
            result.append(MarketView(market=m, options=options, total_pool=int(total), bets_count=int(bets_count)))
        return result
    finally:
        session.close()


def user_open_positions(chat_id: int, user_id: int) -> list[dict]:
    session = SessionLocal()
    try:
        rows = (
            session.query(Bet, Market, MarketOption)
            .join(Market, Market.id == Bet.market_id)
            .join(MarketOption, MarketOption.id == Bet.option_id)
            .filter(Market.chat_id == chat_id, Bet.user_id == user_id)
            .order_by(Bet.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            {
                "bet_id": b.id,
                "market_id": m.id,
                "question": m.question,
                "status": m.status,
                "option_label": o.label,
                "amount": b.amount,
                "payout": b.payout,
                "refunded": bool(b.refunded),
                "created_at": b.created_at,
            }
            for b, m, o in rows
        ]
    finally:
        session.close()


def auto_close_expired() -> int:
    """Переводит open → closed для рынков, у которых closes_at в прошлом. Возвращает количество."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        markets = (
            session.query(Market)
            .filter(Market.status == "open", Market.closes_at <= now)
            .with_for_update()
            .all()
        )
        for m in markets:
            m.status = "closed"
        session.commit()
        return len(markets)
    finally:
        session.close()
