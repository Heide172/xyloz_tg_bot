"""Чат-дуэль: /duel @игрок <ставка> или /duel <ставка> ответом на сообщение.

Форс-резолв (без принятия): монетка 50/50, оба ставят гривны (эскроу),
победитель забирает банк минус комиссия, проигравший улетает в мут на
DUEL_MUTE_MINUTES минут — может слать только стикеры.

Опасная для баланса механика (форс + деньги), поэтому предчеки идут ДО
списания: бот-админ с правом мутить, оба участника — обычные участники
(админа не замутить), оппонент тянет ставку. Иначе — отказ без движения денег.
"""
import asyncio
import time

from aiogram import Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.duel_service import (
    DUEL_COOLDOWN_SEC,
    DUEL_DEFAULT_STAKE,
    DUEL_MUTE_MINUTES,
    duel_chat_sync,
)
from services.markets_service import InsufficientFunds, InvalidArgument
from services.mute_service import bot_can_restrict, member_status, mute_stickers_only
from services.user_card_service import resolve_user_for_card

logger = get_logger(__name__)
router = Router()

# Анти-спам: последний вызов на (chat_id, challenger_tg). In-memory —
# потеря на рестарте не критична (кулдаун ~минута).
_last_challenge: dict[tuple[int, int], float] = {}


def _parse_stake(args: list[str]) -> int:
    """Первый числовой токен → ставка, иначе дефолт."""
    for tok in args:
        if tok.isdigit():
            return int(tok)
    return DUEL_DEFAULT_STAKE


@router.message(Command("duel", "дуэль", ignore_case=True))
async def cmd_duel(msg: types.Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.reply("Дуэль работает только в групповом чате.")
        return
    if not msg.from_user:
        return

    bot = msg.bot
    chat_id = msg.chat.id
    challenger_tg = msg.from_user.id

    now = time.monotonic()
    key = (chat_id, challenger_tg)
    last = _last_challenge.get(key)
    if last is not None and now - last < DUEL_COOLDOWN_SEC:
        left = int(DUEL_COOLDOWN_SEC - (now - last)) + 1
        await msg.reply(f"Остынь — следующая дуэль через {left} c.")
        return

    text = msg.text or ""
    parts = text.split()
    args = parts[1:]
    stake = _parse_stake(args)
    arg_text = " ".join(args) if args else None

    reply = msg.reply_to_message
    reply_to_tg_id = reply.from_user.id if reply and reply.from_user else None
    if reply and reply.from_user and reply.from_user.is_bot:
        await msg.reply("Ботов на дуэль не вызывают.")
        return

    opponent = await asyncio.to_thread(
        resolve_user_for_card, chat_id, arg_text, None, reply_to_tg_id
    )
    if opponent is None or not opponent.tg_id:
        await msg.reply(
            "Кого вызываем? Ответь на сообщение игрока или укажи @ник "
            "(игрок должен был писать в чат)."
        )
        return
    opponent_tg = int(opponent.tg_id)
    if opponent_tg == challenger_tg:
        await msg.reply("Себя вызвать нельзя.")
        return

    if not await bot_can_restrict(bot, chat_id):
        await msg.reply(
            "Не могу мутить: сделайте бота админом с правом ограничивать участников."
        )
        return

    ch_member = await member_status(bot, chat_id, challenger_tg)
    op_member = await member_status(bot, chat_id, opponent_tg)
    if op_member is None or op_member.status in ("left", "kicked"):
        await msg.reply("Этого игрока нет в чате.")
        return
    if op_member.user and op_member.user.is_bot:
        await msg.reply("Ботов на дуэль не вызывают.")
        return
    if ch_member and ch_member.status in ("creator", "administrator"):
        await msg.reply("Ты админ — тебя не замутить, дуэль недоступна.")
        return
    if op_member.status in ("creator", "administrator"):
        await msg.reply("Нельзя вызвать админа — его не замутить.")
        return
    if op_member.status == "restricted" and getattr(op_member, "can_send_messages", True) is False:
        await msg.reply("Игрок уже в муте.")
        return

    _last_challenge[key] = now
    try:
        result = await asyncio.to_thread(
            duel_chat_sync,
            chat_id,
            challenger_tg,
            msg.from_user.username,
            msg.from_user.full_name,
            int(opponent.id),
            stake,
        )
    except (InsufficientFunds, InvalidArgument) as exc:
        await msg.reply(str(exc))
        return
    except Exception:
        logger.exception("duel_chat_sync failed chat=%s", chat_id)
        await msg.reply("Дуэль сорвалась (ошибка). Попробуй позже.")
        return

    ok, err = await mute_stickers_only(
        bot, chat_id, result["loser_tg"], DUEL_MUTE_MINUTES
    )

    lines = [
        f"🪙 Дуэль на {result['stake']}!",
        f"Победил {result['winner_name']} (+{result['prize']} гривен).",
    ]
    if ok:
        lines.append(
            f"{result['loser_name']} улетает в мут на {DUEL_MUTE_MINUTES} мин — "
            f"только стикеры. 🤐"
        )
    else:
        logger.warning(
            "duel #%s: mute failed loser=%s: %s",
            result["id"], result["loser_tg"], err,
        )
        lines.append(
            f"{result['loser_name']} должен был в мут, но замутить не вышло — "
            f"проверьте права бота. Деньги уже переведены."
        )
    await msg.answer("\n".join(lines))
