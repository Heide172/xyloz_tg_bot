"""Экономика чата.

Архитектура:
- user_balance — per (user, chat) текущий баланс.
- economy_tx — append-only журнал всех движений.
- chat_bank — баланс общего банка чата (копит комиссии, потом тратится на казино).

Все изменения балансов должны идти через credit() / debit() / transfer() —
они гарантируют атомарность и запись в economy_tx.
"""
import os
from datetime import datetime
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_bank import ChatBank
from common.models.economy_tx import EconomyTx
from common.models.user import User
from common.models.user_balance import UserBalance

logger = get_logger(__name__)

START_BONUS = int(os.getenv("ECONOMY_START_BONUS", "1000"))
TRANSFER_FEE_PCT = float(os.getenv("TRANSFER_FEE_PCT", "5"))
TRANSFER_FEE_MIN = int(os.getenv("TRANSFER_FEE_MIN", "1"))


def transfer_fee(amount: int) -> int:
    """Комиссия за перевод: max(MIN, ceil(amount × PCT%)). Идёт в банк чата."""
    import math

    return max(TRANSFER_FEE_MIN, math.ceil(amount * TRANSFER_FEE_PCT / 100.0))


class InsufficientFunds(Exception):
    pass


class UnknownUser(Exception):
    pass


# ---------------- low-level ops ----------------


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


# ---------------- high-level API ----------------


def get_balance(user_id: int, chat_id: int, auto_start: bool = True) -> int:
    """Возвращает текущий баланс. При первом обращении начисляет стартовый бонус."""
    session = SessionLocal()
    try:
        bal = (
            session.query(UserBalance)
            .filter(UserBalance.user_id == user_id, UserBalance.chat_id == chat_id)
            .first()
        )
        if bal is not None:
            return bal.balance
        if not auto_start:
            return 0
        # Стартовый бонус.
        bal = _get_or_create_balance(session, user_id, chat_id)
        bal.balance = START_BONUS
        bal.updated_at = datetime.utcnow()
        _log_tx(session, user_id, chat_id, START_BONUS, kind="start_bonus", note="welcome")
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # юзер ещё не создан — пропускаем.
            return 0
        return START_BONUS
    finally:
        session.close()


def credit(user_id: int, chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None) -> int:
    """Пополнить баланс юзера. Возвращает новый баланс."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        bal.balance += amount
        bal.updated_at = datetime.utcnow()
        _log_tx(session, user_id, chat_id, amount, kind=kind, ref_id=ref_id, note=note)
        session.commit()
        return bal.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def debit(user_id: int, chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None) -> int:
    """Списать с баланса. Бросает InsufficientFunds если не хватает. Возвращает новый баланс."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < amount:
            raise InsufficientFunds(f"balance={bal.balance} < amount={amount}")
        bal.balance -= amount
        bal.updated_at = datetime.utcnow()
        _log_tx(session, user_id, chat_id, -amount, kind=kind, ref_id=ref_id, note=note)
        session.commit()
        return bal.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def transfer(from_user_id: int, to_user_id: int, chat_id: int, amount: int, kind: str = "transfer", note: str | None = None) -> tuple[int, int]:
    """Атомарный перевод между юзерами. Возвращает (from_new_balance, to_new_balance)."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    if from_user_id == to_user_id:
        raise ValueError("self-transfer not allowed")
    session = SessionLocal()
    try:
        sender = _get_or_create_balance(session, from_user_id, chat_id)
        if sender.balance < amount:
            raise InsufficientFunds(f"balance={sender.balance} < amount={amount}")
        receiver = _get_or_create_balance(session, to_user_id, chat_id)
        sender.balance -= amount
        receiver.balance += amount
        sender.updated_at = datetime.utcnow()
        receiver.updated_at = datetime.utcnow()
        _log_tx(session, from_user_id, chat_id, -amount, kind=kind, ref_id=str(to_user_id), note=note)
        _log_tx(session, to_user_id, chat_id, amount, kind=kind, ref_id=str(from_user_id), note=note)
        session.commit()
        return sender.balance, receiver.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def transfer_with_fee(
    from_user_id: int, to_user_id: int, chat_id: int, amount: int, note: str | None = None
) -> dict:
    """Перевод с комиссией. Отправитель платит amount + fee, получатель
    получает amount, fee уходит в банк чата. Атомарно."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    if from_user_id == to_user_id:
        raise ValueError("self-transfer not allowed")
    fee = transfer_fee(amount)
    total = amount + fee
    session = SessionLocal()
    try:
        sender = _get_or_create_balance(session, from_user_id, chat_id)
        if sender.balance < total:
            raise InsufficientFunds(
                f"Нужно {total} (перевод {amount} + комиссия {fee}), у тебя {sender.balance}"
            )
        receiver = _get_or_create_balance(session, to_user_id, chat_id)
        bank = _get_or_create_bank(session, chat_id)
        now = datetime.utcnow()
        sender.balance -= total
        receiver.balance += amount
        bank.balance += fee
        sender.updated_at = receiver.updated_at = bank.updated_at = now
        _log_tx(session, from_user_id, chat_id, -total, kind="transfer_out",
                ref_id=str(to_user_id), note=note)
        _log_tx(session, to_user_id, chat_id, amount, kind="transfer_in",
                ref_id=str(from_user_id), note=note)
        _log_tx(session, None, chat_id, fee, kind="transfer_fee",
                ref_id=str(from_user_id), note=f"комиссия перевода {amount}")
        session.commit()
        return {
            "amount": amount,
            "fee": fee,
            "total": total,
            "sender_balance": sender.balance,
            "receiver_balance": receiver.balance,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def deposit_to_bank(chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None) -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = SessionLocal()
    try:
        bank = _get_or_create_bank(session, chat_id)
        bank.balance += amount
        bank.updated_at = datetime.utcnow()
        _log_tx(session, None, chat_id, amount, kind=kind, ref_id=ref_id, note=note)
        session.commit()
        return bank.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def withdraw_from_bank(chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None) -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = SessionLocal()
    try:
        bank = _get_or_create_bank(session, chat_id)
        if bank.balance < amount:
            raise InsufficientFunds(f"bank balance={bank.balance} < amount={amount}")
        bank.balance -= amount
        bank.updated_at = datetime.utcnow()
        _log_tx(session, None, chat_id, -amount, kind=kind, ref_id=ref_id, note=note)
        session.commit()
        return bank.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def user_to_bank(user_id: int, chat_id: int, amount: int, kind: str, ref_id: str | None = None, note: str | None = None) -> tuple[int, int]:
    """Списать с юзера → положить в банк чата атомарно. Возвращает (user_balance, bank_balance)."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < amount:
            raise InsufficientFunds(f"balance={bal.balance} < amount={amount}")
        bank = _get_or_create_bank(session, chat_id)
        bal.balance -= amount
        bank.balance += amount
        bal.updated_at = datetime.utcnow()
        bank.updated_at = datetime.utcnow()
        _log_tx(session, user_id, chat_id, -amount, kind=f"{kind}_user", ref_id=ref_id, note=note)
        _log_tx(session, None, chat_id, amount, kind=f"{kind}_bank", ref_id=ref_id, note=note)
        session.commit()
        return bal.balance, bank.balance
    finally:
        session.close()


# ---------------- read-only ----------------


def get_chat_bank(chat_id: int) -> int:
    session = SessionLocal()
    try:
        row = session.query(ChatBank).filter(ChatBank.chat_id == chat_id).first()
        return row.balance if row else 0
    finally:
        session.close()


def leaderboard(chat_id: int, limit: int = 10) -> list[tuple[User, int]]:
    session = SessionLocal()
    try:
        rows = (
            session.query(User, UserBalance.balance)
            .join(UserBalance, UserBalance.user_id == User.id)
            .filter(UserBalance.chat_id == chat_id)
            .order_by(UserBalance.balance.desc())
            .limit(limit)
            .all()
        )
        return [(u, int(b)) for u, b in rows]
    finally:
        session.close()


def chat_economy_summary(chat_id: int) -> dict:
    session = SessionLocal()
    try:
        total_users = (
            session.query(func.count(UserBalance.user_id))
            .filter(UserBalance.chat_id == chat_id)
            .scalar()
        ) or 0
        total_in_users = (
            session.query(func.coalesce(func.sum(UserBalance.balance), 0))
            .filter(UserBalance.chat_id == chat_id)
            .scalar()
        ) or 0
        bank = session.query(ChatBank).filter(ChatBank.chat_id == chat_id).first()
        bank_balance = bank.balance if bank else 0
        last_txs = (
            session.query(EconomyTx)
            .filter(EconomyTx.chat_id == chat_id)
            .order_by(EconomyTx.created_at.desc())
            .limit(5)
            .all()
        )
        return {
            "users": int(total_users),
            "total_in_users": int(total_in_users),
            "bank": int(bank_balance),
            "total_supply": int(total_in_users) + int(bank_balance),
            "last_txs": last_txs,
        }
    finally:
        session.close()


def resolve_user_by_username(username: str) -> User | None:
    username = username.lstrip("@").strip()
    if not username:
        return None
    session = SessionLocal()
    try:
        return session.query(User).filter(func.lower(User.username) == username.lower()).first()
    finally:
        session.close()
