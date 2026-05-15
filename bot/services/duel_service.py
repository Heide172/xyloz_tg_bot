"""PvP-дуэль 1v1. Эскроу ставок, coinflip, комиссия в банк чата."""
import json
import math
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.duel import Duel
from common.models.user import User
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    MarketError,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)
_rng = secrets.SystemRandom()

DUEL_MIN_STAKE = int(os.getenv("DUEL_MIN_STAKE", "10"))
DUEL_MAX_STAKE = int(os.getenv("DUEL_MAX_STAKE", "100000"))
DUEL_FEE_PCT = float(os.getenv("DUEL_FEE_PCT", "5"))

_bot_username: str | None = None


def _tg_token() -> str:
    t = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    return t


def _get_bot_username() -> str | None:
    global _bot_username
    if _bot_username:
        return _bot_username
    try:
        url = f"https://api.telegram.org/bot{_tg_token()}/getMe"
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            _bot_username = body["result"]["username"]
    except Exception:
        logger.exception("getMe failed")
    return _bot_username


def _announce_challenge(chat_id: int, challenger: str, opponent: str, stake: int) -> None:
    """Анонс вызова в чат с deep-link кнопкой прямо в /duel."""
    uname = _get_bot_username()
    text = (
        f"⚔️ {challenger} вызывает {opponent} на дуэль!\n"
        f"Ставка: {stake} гривен. 50/50, победитель забирает банк."
    )
    params = {"chat_id": chat_id, "text": text}
    if uname:
        startapp = f"{chat_id}_duel"
        params["reply_markup"] = json.dumps(
            {
                "inline_keyboard": [
                    [{"text": "⚔️ Открыть дуэль", "url": f"https://t.me/{uname}?startapp={startapp}"}]
                ]
            }
        )
    try:
        url = f"https://api.telegram.org/bot{_tg_token()}/sendMessage"
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"User-Agent": "xyloz-bot-api/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            b = json.loads(resp.read().decode("utf-8"))
        if not b.get("ok"):
            logger.warning("duel announce failed: %s", b)
    except Exception:
        logger.exception("duel announce error chat=%s", chat_id)


class DuelError(MarketError):
    pass


def _name(u: User | None) -> str:
    if not u:
        return "?"
    if u.username:
        return "@" + u.username
    return u.fullname or f"id{u.id}"


def _duel_dict(session, d: Duel) -> dict:
    ch = session.query(User).filter(User.id == d.challenger_id).first()
    op = session.query(User).filter(User.id == d.opponent_id).first()
    return {
        "id": int(d.id),
        "stake": int(d.stake),
        "status": d.status,
        "challenger_id": int(d.challenger_id) if d.challenger_id else None,
        "opponent_id": int(d.opponent_id) if d.opponent_id else None,
        "challenger": _name(ch),
        "opponent": _name(op),
        "winner_id": int(d.winner_id) if d.winner_id else None,
        "commission": int(d.commission),
        "created_at": d.created_at.isoformat(),
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
    }


def challenge_sync(challenger_id: int, chat_id: int, opponent_id: int, stake: int) -> dict:
    if challenger_id == opponent_id:
        raise InvalidArgument("Нельзя вызвать самого себя")
    if not (DUEL_MIN_STAKE <= stake <= DUEL_MAX_STAKE):
        raise InvalidArgument(f"Ставка {DUEL_MIN_STAKE}..{DUEL_MAX_STAKE}")
    session = SessionLocal()
    try:
        ch_bal = _get_or_create_balance(session, challenger_id, chat_id)
        if ch_bal.balance < stake:
            raise InsufficientFunds(f"Нужно {stake}, у тебя {ch_bal.balance}")
        # один активный вызов между этой парой за раз
        dup = (
            session.query(Duel)
            .filter(
                Duel.chat_id == chat_id,
                Duel.status == "pending",
                Duel.challenger_id == challenger_id,
                Duel.opponent_id == opponent_id,
            )
            .first()
        )
        if dup:
            raise InvalidArgument("Уже есть активный вызов этому игроку")
        ch_bal.balance -= stake  # эскроу
        ch_bal.updated_at = datetime.utcnow()
        d = Duel(
            chat_id=chat_id,
            challenger_id=challenger_id,
            opponent_id=opponent_id,
            stake=stake,
            status="pending",
        )
        session.add(d)
        session.flush()
        _log_tx(session, challenger_id, chat_id, -stake,
                kind="duel_stake_hold", ref_id=str(d.id))
        session.commit()
        result = _duel_dict(session, d)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    # Анонс в чат вне транзакции (deep-link в /duel)
    _announce_challenge(chat_id, result["challenger"], result["opponent"], stake)
    return result


def _load_pending(session, duel_id: int) -> Duel:
    d = session.query(Duel).filter(Duel.id == duel_id).with_for_update().first()
    if not d:
        raise InvalidArgument("Дуэль не найдена")
    if d.status != "pending":
        raise InvalidArgument(f"Дуэль уже {d.status}")
    return d


def accept_sync(duel_id: int, opponent_id: int) -> dict:
    session = SessionLocal()
    try:
        d = _load_pending(session, duel_id)
        if d.opponent_id != opponent_id:
            raise InvalidArgument("Этот вызов адресован не тебе")
        op_bal = _get_or_create_balance(session, opponent_id, d.chat_id)
        if op_bal.balance < d.stake:
            raise InsufficientFunds(f"Нужно {d.stake}, у тебя {op_bal.balance}")
        op_bal.balance -= d.stake  # эскроу оппонента
        op_bal.updated_at = datetime.utcnow()
        _log_tx(session, opponent_id, d.chat_id, -d.stake,
                kind="duel_stake_hold", ref_id=str(d.id))

        pool = d.stake * 2
        commission = max(1, math.ceil(pool * DUEL_FEE_PCT / 100.0))
        prize = pool - commission
        winner_id = _rng.choice([d.challenger_id, opponent_id])
        loser_id = opponent_id if winner_id == d.challenger_id else d.challenger_id

        win_bal = _get_or_create_balance(session, winner_id, d.chat_id)
        win_bal.balance += prize
        win_bal.updated_at = datetime.utcnow()
        bank = _get_or_create_bank(session, d.chat_id)
        bank.balance += commission
        bank.updated_at = datetime.utcnow()

        _log_tx(session, winner_id, d.chat_id, prize,
                kind="duel_win", ref_id=str(d.id),
                note=f"дуэль #{d.id}: выигрыш над {loser_id}")
        _log_tx(session, None, d.chat_id, commission,
                kind="duel_fee", ref_id=str(d.id))

        d.status = "resolved"
        d.winner_id = winner_id
        d.commission = commission
        d.resolved_at = datetime.utcnow()
        session.flush()
        result = _duel_dict(session, d)
        result["prize"] = prize
        result["you_won"] = winner_id == opponent_id
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _refund(session, d: Duel) -> None:
    """Вернуть эскроу challenger'у."""
    ch_bal = _get_or_create_balance(session, d.challenger_id, d.chat_id)
    ch_bal.balance += d.stake
    ch_bal.updated_at = datetime.utcnow()
    _log_tx(session, d.challenger_id, d.chat_id, d.stake,
            kind="duel_refund", ref_id=str(d.id))


def decline_sync(duel_id: int, opponent_id: int) -> dict:
    session = SessionLocal()
    try:
        d = _load_pending(session, duel_id)
        if d.opponent_id != opponent_id:
            raise InvalidArgument("Этот вызов адресован не тебе")
        _refund(session, d)
        d.status = "declined"
        d.resolved_at = datetime.utcnow()
        session.flush()
        r = _duel_dict(session, d)
        session.commit()
        return r
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def cancel_sync(duel_id: int, challenger_id: int) -> dict:
    session = SessionLocal()
    try:
        d = _load_pending(session, duel_id)
        if d.challenger_id != challenger_id:
            raise InvalidArgument("Это не твой вызов")
        _refund(session, d)
        d.status = "cancelled"
        d.resolved_at = datetime.utcnow()
        session.flush()
        r = _duel_dict(session, d)
        session.commit()
        return r
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_sync(user_id: int, chat_id: int) -> dict:
    session = SessionLocal()
    try:
        incoming = (
            session.query(Duel)
            .filter(Duel.chat_id == chat_id, Duel.status == "pending",
                    Duel.opponent_id == user_id)
            .order_by(Duel.created_at.desc())
            .all()
        )
        outgoing = (
            session.query(Duel)
            .filter(Duel.chat_id == chat_id, Duel.status == "pending",
                    Duel.challenger_id == user_id)
            .order_by(Duel.created_at.desc())
            .all()
        )
        history = (
            session.query(Duel)
            .filter(
                Duel.chat_id == chat_id,
                Duel.status.in_(["resolved", "declined", "cancelled"]),
                (Duel.challenger_id == user_id) | (Duel.opponent_id == user_id),
            )
            .order_by(Duel.resolved_at.desc())
            .limit(15)
            .all()
        )
        return {
            "incoming": [_duel_dict(session, d) for d in incoming],
            "outgoing": [_duel_dict(session, d) for d in outgoing],
            "history": [_duel_dict(session, d) for d in history],
            "me": user_id,
        }
    finally:
        session.close()
