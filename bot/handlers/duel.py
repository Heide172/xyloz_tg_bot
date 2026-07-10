"""Чат-дуэль: /duel @игрок <ставка> или /duel <ставка> ответом на сообщение.

Форс-резолв (без принятия): монетка 50/50, оба ставят гривны (эскроу),
победитель забирает банк минус комиссия, проигравший улетает в мут на
DUEL_MUTE_MINUTES минут — может слать только стикеры.

Опасная для баланса механика (форс + деньги), поэтому предчеки идут ДО
списания: бот — админ с правом мутить, оба участника мутибельны, оппонент
тянет ставку. Иначе — отказ без движения денег.

Тег-админов (держателей custom_title из механики тегов) мутить можно:
apply_duel_mute снимет тег + демоутит + restrict, а тег вернёт sweep
(tag_service.restore_due_duel_tags). Реальных модераторов/владельца — нет.
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
from services.mute_service import (
    apply_duel_mute,
    bot_admin_rights,
    is_tag_admin,
    member_status,
    mute_block_reason,
)
from services.user_card_service import resolve_user_for_card

logger = get_logger(__name__)
router = Router()

# Анти-спам: последний вызов на (chat_id, challenger_tg). In-memory —
# потеря на рестарте не критична (кулдаун ~минута).
_last_challenge: dict[tuple[int, int], float] = {}

# Причина отказа (код из mute_block_reason) → текст для оппонента.
_OPPONENT_BLOCK = {
    "absent": "Этого игрока нет в чате.",
    "bot": "Ботов на дуэль не вызывают.",
    "owner": "Нельзя вызвать владельца чата — его не замутить.",
    "real_admin": "Нельзя вызвать реального админа — его не трогаем.",
    "muted": "Игрок уже в муте.",
}


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
    if bot_rights is None or not getattr(bot_rights, "can_restrict_members", False):
        await msg.reply(
            "Не могу мутить: сделайте бота админом с правом ограничивать участников."
        )
        return

    ch_member = await member_status(bot, chat_id, challenger_tg)
    op_member = await member_status(bot, chat_id, opponent_tg)

    op_block = mute_block_reason(op_member)
    if op_block:
        await msg.reply(_OPPONENT_BLOCK[op_block])
        return
    ch_block = mute_block_reason(ch_member)
    if ch_block in ("owner", "real_admin"):
        await msg.reply("Ты сам админ или владелец — тебя не замутить, дуэль недоступна.")
        return
    if ch_block == "muted":
        await msg.reply("Ты сейчас в муте.")
        return

    # Демоут/возврат тега тег-админа требует права назначать администраторов.
    if (is_tag_admin(op_member) or is_tag_admin(ch_member)) and not getattr(
        bot_rights, "can_promote_members", False
    ):
        await msg.reply("Для мута тег-админа боту нужно право назначать администраторов.")
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
        tag_note = " (тег вернём после мута)" if is_tag_admin(loser_member) else ""
        lines.append(
            f"{result['loser_name']} улетает в мут на {DUEL_MUTE_MINUTES} мин — "
            f"только стикеры.{tag_note} 🤐"
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
