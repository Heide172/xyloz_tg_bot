"""Команды экономики: /balance, /leaderboard, /economy, /transfer, /admin_adjust."""
import html
import re

from aiogram import Router, types
from aiogram.filters import Command

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.user import User
from services.admin_service import is_admin_tg_id
from services.economy_service import (
    InsufficientFunds,
    chat_economy_summary,
    credit,
    debit,
    get_balance,
    leaderboard,
    resolve_user_by_username,
    transfer,
)

router = Router()
logger = get_logger(__name__)


def _author_name(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


async def _send_mono(msg: types.Message, text: str):
    safe = html.escape(text)
    await msg.answer(f"<pre>{safe}</pre>", parse_mode="HTML")


def _ensure_db_user(tg_user) -> User:
    """Гарантирует наличие пользователя в БД, возвращает User."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.tg_id == tg_user.id).first()
        if user is None:
            user = User(tg_id=tg_user.id, username=tg_user.username, fullname=tg_user.full_name)
            session.add(user)
            session.commit()
            session.refresh(user)
        return user
    finally:
        session.close()


# ---------------- /balance ----------------


@router.message(Command("balance"))
async def cmd_balance(msg: types.Message):
    if not msg.from_user:
        return
    user = _ensure_db_user(msg.from_user)
    bal = get_balance(user.id, msg.chat.id, auto_start=True)
    await _send_mono(msg, f"{_author_name(user)}: {bal} коинов")


# ---------------- /leaderboard ----------------


@router.message(Command("leaderboard"))
async def cmd_leaderboard(msg: types.Message):
    rows = leaderboard(msg.chat.id, limit=15)
    if not rows:
        await _send_mono(msg, "Лидерборд пуст. Никто ещё не получил баланс.")
        return
    max_name = max((len(_author_name(u)) for u, _ in rows), default=10)
    lines = [f"Лидерборд чата (top {len(rows)})", ""]
    for i, (u, b) in enumerate(rows, 1):
        lines.append(f"{i:>2}. {_author_name(u):<{max_name}}  {b:>8} коинов")
    await _send_mono(msg, "\n".join(lines))


# ---------------- /economy ----------------


@router.message(Command("economy"))
async def cmd_economy(msg: types.Message):
    s = chat_economy_summary(msg.chat.id)
    lines = [
        "Экономика чата",
        "",
        f"Пользователей с балансом: {s['users']}",
        f"Сумма у пользователей:    {s['total_in_users']}",
        f"Банк чата:                {s['bank']}",
        f"Общая денежная масса:     {s['total_supply']}",
    ]
    if s["last_txs"]:
        lines.append("")
        lines.append("Последние операции:")
        for tx in s["last_txs"]:
            ts = tx.created_at.strftime("%Y-%m-%d %H:%M")
            sign = "+" if tx.amount >= 0 else ""
            note = f" — {tx.note}" if tx.note else ""
            lines.append(f"  {ts}  {sign}{tx.amount:>6} [{tx.kind}]{note}")
    await _send_mono(msg, "\n".join(lines))


# ---------------- /transfer ----------------


@router.message(Command("transfer"))
async def cmd_transfer(msg: types.Message):
    if not msg.from_user:
        return
    parts = (msg.text or "").split()
    if len(parts) < 3:
        await msg.answer("Использование: /transfer @username <сумма>")
        return
    target_arg = parts[1]
    try:
        amount = int(parts[2])
    except ValueError:
        await msg.answer("Сумма должна быть целым числом.")
        return
    if amount <= 0:
        await msg.answer("Сумма должна быть положительной.")
        return

    target_user = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_tg_user = msg.reply_to_message.from_user
        target_user = _ensure_db_user(target_tg_user)
    else:
        m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", target_arg)
        if not m:
            await msg.answer("Укажи @username или ответь /transfer на сообщение.")
            return
        target_user = resolve_user_by_username(m.group(1))
        if target_user is None:
            await msg.answer(f"Пользователь {target_arg} не найден.")
            return

    sender = _ensure_db_user(msg.from_user)
    if sender.id == target_user.id:
        await msg.answer("Себе переводить нельзя.")
        return

    # Авто-стартовый бонус если первый раз
    get_balance(sender.id, msg.chat.id, auto_start=True)

    try:
        from_bal, to_bal = transfer(
            from_user_id=sender.id,
            to_user_id=target_user.id,
            chat_id=msg.chat.id,
            amount=amount,
            kind="transfer",
            note=f"from {_author_name(sender)} to {_author_name(target_user)}",
        )
    except InsufficientFunds as exc:
        await msg.answer(f"Недостаточно средств: {exc}")
        return
    except Exception as exc:
        logger.exception("transfer failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    await _send_mono(
        msg,
        f"{_author_name(sender)} → {_author_name(target_user)}: {amount} коинов\n"
        f"Баланс {_author_name(sender)}:        {from_bal}\n"
        f"Баланс {_author_name(target_user)}:   {to_bal}",
    )


# ---------------- /admin_adjust ----------------


@router.message(Command("admin_adjust"))
async def cmd_admin_adjust(msg: types.Message):
    if not msg.from_user or not is_admin_tg_id(msg.from_user.id):
        await msg.answer("Только для админов бота.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 3:
        await msg.answer("Использование: /admin_adjust @username ±<сумма> [note]")
        return
    target_arg = parts[1]
    try:
        amount = int(parts[2])
    except ValueError:
        await msg.answer("Сумма должна быть целым числом со знаком (±).")
        return
    if amount == 0:
        await msg.answer("Сумма не должна быть нулевой.")
        return
    note = " ".join(parts[3:]) if len(parts) > 3 else None

    target_user = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_user = _ensure_db_user(msg.reply_to_message.from_user)
    else:
        m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", target_arg)
        if not m:
            await msg.answer("Укажи @username или ответь /admin_adjust на сообщение.")
            return
        target_user = resolve_user_by_username(m.group(1))
        if target_user is None:
            await msg.answer(f"Пользователь {target_arg} не найден.")
            return

    try:
        if amount > 0:
            new_balance = credit(
                user_id=target_user.id,
                chat_id=msg.chat.id,
                amount=amount,
                kind="admin_adjust",
                note=note,
            )
        else:
            new_balance = debit(
                user_id=target_user.id,
                chat_id=msg.chat.id,
                amount=-amount,
                kind="admin_adjust",
                note=note,
            )
    except InsufficientFunds as exc:
        await msg.answer(f"Не хватает средств: {exc}")
        return
    except Exception as exc:
        logger.exception("admin_adjust failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    sign = "+" if amount > 0 else ""
    await _send_mono(
        msg,
        f"admin_adjust: {_author_name(target_user)} {sign}{amount} (новый баланс: {new_balance})"
        + (f"\nnote: {note}" if note else ""),
    )
