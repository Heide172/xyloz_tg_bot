"""Чат-дуэль: /duel @игрок <ставка> или /duel <ставка> ответом на сообщение.

Форс-резолв (без принятия): монетка 50/50, оба ставят гривны (эскроу),
победитель забирает банк минус комиссия, проигравший улетает в мут на
DUEL_MUTE_MINUTES минут — может слать только стикеры.

Опасная для баланса механика (форс + деньги), поэтому предчеки идут ДО
списания: у бота есть права под нужную стратегию мута обоих участников,
оппонент тянет ставку, никто ещё не в муте. Иначе — отказ без движения денег.

Мутибельны все, кроме отсутствующих и ботов. Стратегия зависит от типа
проигравшего (mute_service.mute_strategy): обычный участник — нативный
restrict; админ, кого бот может разжаловать — снять права+тег/restrict/вернуть
после; владелец и ручные админы (разжаловать нельзя) — софт-мут (удаление
не-стикерных сообщений через DuelMuteMiddleware).
"""
import asyncio
import time

from aiogram import BaseMiddleware, Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.duel_service import (
    DUEL_COOLDOWN_SEC,
    DUEL_DEFAULT_STAKE,
    DUEL_MUTE_MINUTES,
    duel_chat_sync,
)
from services.markets_service import InsufficientFunds, InvalidArgument
from services.mute_service import (
    apply_duel_mute,
    bot_admin_rights,
    is_already_muted,
    is_soft_muted,
    member_status,
    mute_strategy,
)
from services.user_card_service import resolve_user_for_card

logger = get_logger(__name__)
router = Router()

# Анти-спам: последний вызов на (chat_id, challenger_tg). In-memory —
# потеря на рестарте не критична (кулдаун ~минута).
_last_challenge: dict[tuple[int, int], float] = {}

# Право бота, нужное под каждую стратегию мута (человекочитаемо для отказа).
_RIGHT_FOR_STRATEGY = {
    "native": ("can_restrict_members", "ограничивать участников"),
    "hard_admin": ("can_promote_members", "назначать администраторов"),
    "soft": ("can_delete_messages", "удалять сообщения"),
}


class DuelMuteMiddleware(BaseMiddleware):
    """Софт-мут: 15 минут удаляем не-стикерные сообщения проигравшего, если
    его нельзя было замутить нативно (владелец / ручной админ)."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        chat = getattr(event, "chat", None)
        if (
            user is not None
            and chat is not None
            and event.sticker is None
            and is_soft_muted(chat.id, user.id)
        ):
            try:
                await event.delete()
            except Exception:
                logger.warning("soft-mute delete failed chat=%s user=%s", chat.id, user.id)
            return None  # съедаем сообщение — дальше не пускаем
        return await handler(event, data)


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

    bot_rights = await bot_admin_rights(bot, chat_id)
    if bot_rights is None:
        await msg.reply("Не могу мутить: бот должен быть админом чата.")
        return

    ch_member = await member_status(bot, chat_id, challenger_tg)
    op_member = await member_status(bot, chat_id, opponent_tg)

    op_strat = mute_strategy(op_member)
    if op_strat == "absent":
        await msg.reply("Этого игрока нет в чате.")
        return
    if op_strat == "bot":
        await msg.reply("Ботов на дуэль не вызывают.")
        return
    if is_already_muted(chat_id, op_member):
        await msg.reply("Игрок уже в муте.")
        return

    ch_strat = mute_strategy(ch_member)
    if is_already_muted(chat_id, ch_member):
        await msg.reply("Ты сейчас в муте.")
        return

    # Проигравшего заранее не знаем — у бота должны быть права под стратегию
    # мута ОБОИХ участников.
    missing = set()
    for strat in (op_strat, ch_strat):
        right = _RIGHT_FOR_STRATEGY.get(strat)
        if right and not getattr(bot_rights, right[0], False):
            missing.add(right[1])
    if missing:
        await msg.reply("Не могу мутить: боту нужно право — " + ", ".join(sorted(missing)) + ".")
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

    loser_tg = result["loser_tg"]
    loser_member = ch_member if loser_tg == challenger_tg else op_member
    ok, err = await apply_duel_mute(
        bot, chat_id, loser_tg, DUEL_MUTE_MINUTES, loser_member
    )

    lines = [
        f"🪙 Дуэль на {result['stake']}!",
        f"Победил {result['winner_name']} (+{result['prize']} гривен).",
    ]
    if ok:
        note = " (права вернём после мута)" if mute_strategy(loser_member) == "hard_admin" else ""
        lines.append(
            f"{result['loser_name']} улетает в мут на {DUEL_MUTE_MINUTES} мин — "
            f"только стикеры.{note} 🤐"
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
