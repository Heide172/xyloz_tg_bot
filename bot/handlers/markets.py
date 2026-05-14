"""Команды для internal markets: /market_create, /markets, /market, /bet, /portfolio, /market_resolve, /market_cancel."""
import html

from aiogram import Router, types
from aiogram.filters import Command

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.market import Market
from common.models.user import User
from services.admin_service import is_admin_tg_id
from services.external_markets import EXTERNAL_IMPORT_FEE, import_market
from services.markets_service import (
    MARKET_CREATION_FEE,
    MARKET_MIN_BET,
    MARKET_RESOLUTION_FEE_PCT,
    InsufficientFunds,
    InvalidArgument,
    MarketClosed,
    MarketNotFound,
    cancel_market,
    create_market,
    get_market,
    list_markets,
    parse_duration,
    place_bet,
    resolve_market,
    user_open_positions,
)

router = Router()
logger = get_logger(__name__)


def _ensure_db_user(tg_user) -> User:
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


def _author_name(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


async def _send_mono(msg: types.Message, text: str):
    safe = html.escape(text)
    await msg.answer(f"<pre>{safe}</pre>", parse_mode="HTML")


def _format_market_card(view) -> str:
    m = view.market
    lines = [
        f"Рынок #{m.id}  [{m.status}]",
        f"Q: {m.question}",
        "",
    ]
    for idx, o in enumerate(view.options, 1):
        share = (o.pool / view.total_pool * 100) if view.total_pool else 0
        lines.append(f"  {idx}. {o.label:<30}  пул {o.pool:>7}  ({share:.1f}%)")
    lines.append("")
    lines.append(f"Total pool: {view.total_pool}  Ставок: {view.bets_count}")
    lines.append(f"Закроется: {m.closes_at:%Y-%m-%d %H:%M} UTC")
    if m.winning_option_id is not None:
        win = next((o for o in view.options if o.id == m.winning_option_id), None)
        if win:
            lines.append(f"Победила: {win.label}")
    return "\n".join(lines)


# ---------------- /market_create ----------------


HELP_CREATE = (
    "Создание рынка:\n"
    "/market_create вопрос | опция1 | опция2 | <длительность>\n"
    "Длительность: 7d / 12h / 90m\n"
    f"Комиссия за создание: {MARKET_CREATION_FEE} коинов (идёт в банк чата).\n"
    "Опций — от 2 до 6."
)


@router.message(Command("market_create"))
async def cmd_market_create(msg: types.Message):
    if not msg.from_user:
        return
    text = msg.text or ""
    body = text.split(maxsplit=1)
    if len(body) < 2:
        await _send_mono(msg, HELP_CREATE)
        return
    parts = [p.strip() for p in body[1].split("|")]
    if len(parts) < 4:
        await _send_mono(msg, HELP_CREATE)
        return
    question, *rest = parts
    duration_arg = rest[-1]
    options = rest[:-1]

    try:
        duration = parse_duration(duration_arg)
    except InvalidArgument as exc:
        await msg.answer(str(exc))
        return

    user = _ensure_db_user(msg.from_user)
    try:
        result = create_market(
            chat_id=msg.chat.id,
            creator_user_id=user.id,
            question=question,
            options=options,
            duration=duration,
        )
    except InsufficientFunds as exc:
        await msg.answer(str(exc))
        return
    except InvalidArgument as exc:
        await msg.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("market_create failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    options_str = "\n".join(f"  {i+1}. {label}" for i, (_oid, label) in enumerate(result.options))
    await _send_mono(
        msg,
        f"Рынок #{result.market_id} создан\n"
        f"Q: {question}\n"
        f"Опции:\n{options_str}\n"
        f"Комиссия списана: {result.fee_charged} коинов\n"
        f"Ставить: /bet {result.market_id} <N> <сумма>",
    )


# ---------------- /markets ----------------


@router.message(Command("markets"))
async def cmd_markets(msg: types.Message):
    parts = (msg.text or "").split()
    status = None
    if len(parts) > 1:
        s = parts[1].lower()
        if s in ("open", "closed", "resolved", "cancelled", "all"):
            status = None if s == "all" else s
        else:
            await msg.answer("status: open|closed|resolved|cancelled|all")
            return
    if status is None and len(parts) <= 1:
        status = "open"
    views = list_markets(msg.chat.id, status=status, limit=15)
    if not views:
        await _send_mono(msg, f"Рынков нет (status={status or 'all'}).")
        return
    lines = [f"Рынки чата (status={status or 'all'}, {len(views)} шт)", ""]
    for v in views:
        m = v.market
        line = f"#{m.id:<4} [{m.status:<9}] pool={v.total_pool:<7} bets={v.bets_count:<3}  {m.question[:60]}"
        lines.append(line)
    lines.append("")
    lines.append("Детали: /market <id>")
    await _send_mono(msg, "\n".join(lines))


# ---------------- /market <id> ----------------


@router.message(Command("market"))
async def cmd_market(msg: types.Message):
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("Использование: /market <id>")
        return
    try:
        market_id = int(parts[1])
    except ValueError:
        await msg.answer("id должен быть числом")
        return
    view = get_market(market_id)
    if view is None or view.market.chat_id != msg.chat.id:
        await msg.answer(f"Рынок #{market_id} не найден в этом чате.")
        return
    await _send_mono(msg, _format_market_card(view))


# ---------------- /bet ----------------


@router.message(Command("bet"))
async def cmd_bet(msg: types.Message):
    if not msg.from_user:
        return
    parts = (msg.text or "").split()
    if len(parts) < 4:
        await msg.answer(f"Использование: /bet <market_id> <option_idx> <amount>\nМин. ставка: {MARKET_MIN_BET}")
        return
    try:
        market_id = int(parts[1])
        option_idx = int(parts[2])
        amount = int(parts[3])
    except ValueError:
        await msg.answer("Аргументы должны быть числами")
        return

    user = _ensure_db_user(msg.from_user)
    try:
        result = place_bet(
            market_id=market_id,
            option_position=option_idx,
            user_id=user.id,
            amount=amount,
        )
    except (MarketNotFound, MarketClosed, InvalidArgument, InsufficientFunds) as exc:
        await msg.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("bet failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    await _send_mono(
        msg,
        f"Ставка принята: #{result['bet_id']}\n"
        f"Рынок #{result['market_id']}, опция: {result['option_label']}\n"
        f"Сумма: {amount}, баланс после: {result['user_balance_after']}\n"
        f"Пул опции сейчас: {result['option_pool_after']}",
    )


# ---------------- /portfolio ----------------


@router.message(Command("portfolio"))
async def cmd_portfolio(msg: types.Message):
    if not msg.from_user:
        return
    user = _ensure_db_user(msg.from_user)
    positions = user_open_positions(chat_id=msg.chat.id, user_id=user.id)
    if not positions:
        await _send_mono(msg, "У тебя нет ставок в этом чате.")
        return
    lines = [f"Ставки {_author_name(user)}", ""]
    for p in positions[:20]:
        status_line = f"[{p['status']}]"
        payout_line = ""
        if p["status"] == "resolved":
            payout = p["payout"] or 0
            sign = "+" if payout > 0 else ""
            payout_line = f"  payout: {sign}{payout}"
        elif p["refunded"]:
            payout_line = f"  refunded: {p['amount']}"
        q = p["question"][:50] + ("…" if len(p["question"]) > 50 else "")
        lines.append(f"#{p['market_id']} {status_line:<11} {q}")
        lines.append(f"  ставка {p['amount']} на «{p['option_label']}»{payout_line}")
    await _send_mono(msg, "\n".join(lines))


# ---------------- /market_resolve (admin) ----------------


@router.message(Command("market_resolve"))
async def cmd_market_resolve(msg: types.Message):
    if not msg.from_user or not is_admin_tg_id(msg.from_user.id):
        await msg.answer("Только для админов бота.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 3:
        await msg.answer("Использование: /market_resolve <id> <winning_option_idx>")
        return
    try:
        market_id = int(parts[1])
        winning_idx = int(parts[2])
    except ValueError:
        await msg.answer("Аргументы должны быть числами")
        return

    view = get_market(market_id)
    if view is None or view.market.chat_id != msg.chat.id:
        await msg.answer(f"Рынок #{market_id} не найден в этом чате.")
        return

    try:
        result = resolve_market(market_id=market_id, winning_option_position=winning_idx)
    except (MarketNotFound, InvalidArgument) as exc:
        await msg.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("market_resolve failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    if result["total_pool"] == 0:
        await _send_mono(msg, f"Рынок #{market_id} закрыт. Никто не ставил.")
        return
    if result["refunded"]:
        await _send_mono(
            msg,
            f"Рынок #{market_id} закрыт.\nНикто не угадал — все ставки возвращены.",
        )
        return

    lines = [
        f"Рынок #{market_id} закрыт",
        f"Победила: {result['winning_label']}",
        f"Total pool:  {result['total_pool']}",
        f"Комиссия:    {result['commission']} ({MARKET_RESOLUTION_FEE_PCT}% в банк чата)",
        f"Распределено: {result['distributed']}",
        "",
        f"Выплат: {len(result['payouts'])}",
    ]
    # Топ-5 победителей
    sorted_payouts = sorted(result["payouts"], key=lambda x: -x["payout"])[:5]
    if sorted_payouts:
        names = _names_for_user_ids([p["user_id"] for p in sorted_payouts])
        for p in sorted_payouts:
            name = names.get(p["user_id"], f"user#{p['user_id']}")
            lines.append(f"  {name}: ставка {p['bet_amount']} → выплата {p['payout']}")
    await _send_mono(msg, "\n".join(lines))


def _names_for_user_ids(user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    session = SessionLocal()
    try:
        users = session.query(User).filter(User.id.in_(user_ids)).all()
        return {u.id: _author_name(u) for u in users}
    finally:
        session.close()


# ---------------- /market_import ----------------


@router.message(Command("market_import"))
async def cmd_market_import(msg: types.Message):
    if not msg.from_user:
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await _send_mono(
            msg,
            "Использование: /market_import <url>\n"
            f"Поддерживаются: polymarket.com, manifold.markets\n"
            f"Комиссия импорта: {EXTERNAL_IMPORT_FEE} коинов (в банк чата).\n"
            "После импорта рынок резолвится автоматически при закрытии внешнего.",
        )
        return
    url = parts[1].strip()
    user = _ensure_db_user(msg.from_user)
    progress = await msg.answer("Импортирую рынок…")
    try:
        result = await import_market(chat_id=msg.chat.id, creator_user_id=user.id, url=url)
    except (InvalidArgument, InsufficientFunds) as exc:
        await progress.edit_text(str(exc))
        return
    except Exception as exc:
        logger.exception("market_import failed")
        await progress.edit_text(f"Не получилось импортировать: {exc}")
        return

    if result.get("already_imported"):
        await progress.edit_text(f"Этот рынок уже импортирован: #{result['market_id']}. /market {result['market_id']}")
        return

    options_str = "\n".join(f"  {i+1}. {label}" for i, label in enumerate(result["options"]))
    text = (
        f"Импортирован {result['source']}-рынок #{result['market_id']}\n"
        f"Q: {result['question']}\n"
        f"Опции:\n{options_str}\n"
        f"Закрытие: {result['closes_at']:%Y-%m-%d %H:%M} UTC\n"
        + ("Уже разрезолвлен внешне — закроется при следующей проверке.\n" if result["is_resolved"] else "")
        + f"Ставить: /bet {result['market_id']} <N> <сумма>"
    )
    safe = html.escape(text)
    await progress.edit_text(f"<pre>{safe}</pre>", parse_mode="HTML")


# ---------------- /market_cancel (admin) ----------------


@router.message(Command("market_cancel"))
async def cmd_market_cancel(msg: types.Message):
    if not msg.from_user or not is_admin_tg_id(msg.from_user.id):
        await msg.answer("Только для админов бота.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("Использование: /market_cancel <id>")
        return
    try:
        market_id = int(parts[1])
    except ValueError:
        await msg.answer("id должен быть числом")
        return

    view = get_market(market_id)
    if view is None or view.market.chat_id != msg.chat.id:
        await msg.answer(f"Рынок #{market_id} не найден в этом чате.")
        return

    try:
        result = cancel_market(market_id=market_id)
    except (MarketNotFound, InvalidArgument) as exc:
        await msg.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("market_cancel failed")
        await msg.answer(f"Ошибка: {exc}")
        return

    await _send_mono(msg, f"Рынок #{market_id} отменён. Возвращено ставок: {result['refunded']}.")
