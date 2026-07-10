"""Чат-дуэль: /duel @игрок <ставка> или /duel <ставка> ответом на сообщение.

Форс-резолв (без принятия): монетка 50/50, оба ставят гривны (эскроу),
победитель забирает банк минус комиссия, проигравший улетает в мут на
DUEL_MUTE_MINUTES минут — может слать только стикеры.

Опасная для баланса механика (форс + деньги), поэтому предчеки идут ДО
списания: у бота есть права под нужную стратегию мута обоих участников,
атакующий тянет свою ×N-ставку, никто ещё не в муте. Иначе — отказ без
движения денег. Оппонент платёжеспособным быть НЕ обязан — безденежного тоже
можно вызвать (ставит сколько есть), он рискует мутом (см. duel_chat_sync).

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
    DUEL_RING_COOLDOWN_MIN,
    DUELBOT_COOLDOWN_MIN,
    DUELBOT_MIN_STAKE,
    duel_chat_sync,
    duelbot_sync,
)
from services import duel_mute_registry as _reg
from services.admin_service import is_admin_tg_id
from services.markets_service import InsufficientFunds, InvalidArgument
from services.mute_service import (
    apply_duel_mute,
    bot_admin_rights,
    is_already_muted,
    is_soft_muted,
    is_tag_admin,
    member_status,
    mute_strategy,
    unmute_now,
)
from services.user_card_service import resolve_user_for_card

logger = get_logger(__name__)
router = Router()

# Анти-спам: последний вызов на (chat_id, challenger_tg). In-memory —
# потеря на рестарте не критична (кулдаун ~минута).
_last_challenge: dict[tuple[int, int], float] = {}

# «Отмывание ринга»: chat_id -> monotonic-время, когда ринг снова чистый.
# Глобальный кулдаун на весь чат после состоявшегося боя. In-memory —
# рестарт очищает ринг досрочно, для геймплейного кулдауна это ок.
_ring_clean_at: dict[int, float] = {}

# Отдельный кулдаун босс-файта с ботом (chat_id -> monotonic).
_duelbot_ready_at: dict[int, float] = {}


def _fmt_left(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60) + 1} мин"
    return f"{int(seconds)} c"

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

    # Глобальный кулдаун чата: ринг ещё отмывают от прошлого боя.
    clean_at = _ring_clean_at.get(chat_id)
    if clean_at is not None and now < clean_at:
        await msg.reply(
            "🧹 Ринг ещё отмывают от крови прошлой дуэли — "
            f"приходи через {_fmt_left(clean_at - now)}."
        )
        return

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

    # Бой состоялся — ринг «в крови», отмываем DUEL_RING_COOLDOWN_MIN минут.
    _ring_clean_at[chat_id] = now + DUEL_RING_COOLDOWN_MIN * 60

    loser_tg = result["loser_tg"]
    loser_member = ch_member if loser_tg == challenger_tg else op_member
    ok, err = await apply_duel_mute(
        bot, chat_id, loser_tg, DUEL_MUTE_MINUTES, loser_member
    )

    lines = [
        f"🪙 Дуэль! {result['challenger_name']} ставит {result['challenger_stake']} "
        f"против {result['opponent_stake']} у {result['opponent_name']}.",
    ]
    if result["opponent_stake"] == 0:
        lines.append(f"💸 У {result['opponent_name']} пусто — на кону только его мут.")
    lines.append(f"Победил {result['winner_name']} (+{result['prize']} гривен).")
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
    lines.append(f"🧹 Ринг закрыт на отмывание — {DUEL_RING_COOLDOWN_MIN} мин без дуэлей.")
    await msg.answer("\n".join(lines))


# ---------------- ручная модерация: /mute /unmute ----------------


def _display_name(user) -> str:
    if user.username:
        return "@" + user.username
    return user.fullname or f"id{user.tg_id}"


def _parse_minutes(args: list[str], default: int) -> int:
    """Первый токен-длительность: '10' (мин), '10m', '2h', '1d'. Иначе дефолт."""
    for tok in args:
        t = tok.strip().lower()
        try:
            if t.endswith("m"):
                mins = int(t[:-1])
            elif t.endswith("h"):
                mins = int(t[:-1]) * 60
            elif t.endswith("d"):
                mins = int(t[:-1]) * 1440
            elif t.isdigit():
                mins = int(t)
            else:
                continue
        except ValueError:
            continue
        return max(1, min(mins, 366 * 1440))  # Telegram: 30с..366д
    return default


async def _is_moderator(msg: types.Message) -> bool:
    """Бот-админ (BOT_ADMIN_IDS) или реальный админ чата (не тег-холдер)."""
    if not msg.from_user:
        return False
    if is_admin_tg_id(msg.from_user.id):
        return True
    member = await member_status(msg.bot, msg.chat.id, msg.from_user.id)
    if member is None:
        return False
    if member.status == "creator":
        return True
    return member.status == "administrator" and not is_tag_admin(member)


async def _resolve_target(msg: types.Message):
    text = msg.text or ""
    parts = text.split()
    arg_text = " ".join(parts[1:]) if len(parts) > 1 else None
    reply = msg.reply_to_message
    reply_to_tg_id = reply.from_user.id if reply and reply.from_user else None
    return await asyncio.to_thread(
        resolve_user_for_card, msg.chat.id, arg_text, None, reply_to_tg_id
    )


@router.message(Command("mute", ignore_case=True))
async def cmd_mute(msg: types.Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.reply("Только в групповом чате.")
        return
    if not await _is_moderator(msg):
        await msg.reply("Команда только для модераторов чата.")
        return

    bot = msg.bot
    chat_id = msg.chat.id
    minutes = _parse_minutes((msg.text or "").split()[1:], DUEL_MUTE_MINUTES)

    target = await _resolve_target(msg)
    if target is None or not target.tg_id:
        await msg.reply("Кого мутим? Ответь на сообщение игрока или укажи @ник.")
        return
    target_tg = int(target.tg_id)

    bot_rights = await bot_admin_rights(bot, chat_id)
    if bot_rights is None:
        await msg.reply("Бот должен быть админом чата.")
        return
    member = await member_status(bot, chat_id, target_tg)
    if is_already_muted(chat_id, member):
        await msg.reply("Игрок уже в муте — сними /unmute, чтобы перевыдать.")
        return
    strat = mute_strategy(member)
    if strat == "absent":
        await msg.reply("Игрока нет в чате.")
        return
    if strat == "bot":
        await msg.reply("Ботов не мутим.")
        return
    right = _RIGHT_FOR_STRATEGY.get(strat)
    if right and not getattr(bot_rights, right[0], False):
        await msg.reply(f"Не могу: боту нужно право «{right[1]}».")
        return

    ok, err = await apply_duel_mute(bot, chat_id, target_tg, minutes, member)
    if ok:
        await msg.reply(
            f"🔇 {_display_name(target)} в муте на {minutes} мин — только стикеры."
        )
    else:
        await msg.reply(f"Не вышло замутить: {err}")


@router.message(Command("unmute", ignore_case=True))
async def cmd_unmute(msg: types.Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.reply("Только в групповом чате.")
        return
    if not await _is_moderator(msg):
        await msg.reply("Команда только для модераторов чата.")
        return

    target = await _resolve_target(msg)
    if target is None or not target.tg_id:
        await msg.reply("Кого размутить? Ответь на сообщение игрока или укажи @ник.")
        return

    ok, err = await unmute_now(msg.bot, msg.chat.id, int(target.tg_id))
    if ok:
        await msg.reply(f"🔊 {_display_name(target)} размучен.")
    elif err == "не в муте":
        await msg.reply(f"{_display_name(target)} и так не в муте.")
    else:
        await msg.reply(f"Не вышло: {err}")


# ---------------- босс-файт с ботом: /duelbot ----------------


def _parse_bot_stake(args: list[str]) -> int:
    for tok in args:
        if tok.isdigit():
            return int(tok)
    return DUELBOT_MIN_STAKE


@router.message(Command("duelbot", "дуэльбот", ignore_case=True))
async def cmd_duelbot(msg: types.Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.reply("Только в групповом чате.")
        return
    if not msg.from_user:
        return

    bot = msg.bot
    chat_id = msg.chat.id
    challenger_tg = msg.from_user.id

    now = time.monotonic()
    ready = _duelbot_ready_at.get(chat_id)
    if ready is not None and now < ready:
        await msg.reply(
            f"🤖 Бот ещё зализывает раны после прошлого боя — вызов через {_fmt_left(ready - now)}."
        )
        return

    stake = _parse_bot_stake((msg.text or "").split()[1:])

    # Проигравшего игрока надо будет замутить → нужны права под его стратегию.
    bot_rights = await bot_admin_rights(bot, chat_id)
    if bot_rights is None:
        await msg.reply("Бот должен быть админом чата.")
        return
    ch_member = await member_status(bot, chat_id, challenger_tg)
    if is_already_muted(chat_id, ch_member):
        await msg.reply("Ты сейчас в муте.")
        return
    strat = mute_strategy(ch_member)
    right = _RIGHT_FOR_STRATEGY.get(strat)
    if right and not getattr(bot_rights, right[0], False):
        await msg.reply(f"Не могу: боту нужно право «{right[1]}» (замутить при проигрыше).")
        return

    try:
        result = await asyncio.to_thread(
            duelbot_sync,
            chat_id,
            challenger_tg,
            msg.from_user.username,
            msg.from_user.full_name,
            stake,
        )
    except (InsufficientFunds, InvalidArgument) as exc:
        await msg.reply(str(exc))
        return
    except Exception:
        logger.exception("duelbot_sync failed chat=%s", chat_id)
        await msg.reply("Бой с ботом сорвался (ошибка). Попробуй позже.")
        return

    _duelbot_ready_at[chat_id] = now + DUELBOT_COOLDOWN_MIN * 60

    if result["win"]:
        until = int(time.time()) + DUEL_MUTE_MINUTES * 60
        _reg.set_bot_mute(chat_id, until)
        lines = [
            f"🤖💥 {result['challenger_name']} пробил бота!",
            f"Лут из банка: +{result['loot']} гривен (в банке осталось {result['bank_after']}).",
            f"Бот в муте на {DUEL_MUTE_MINUTES} мин — теперь болтает только стикерами. 🤐",
        ]
    else:
        ok, err = await apply_duel_mute(bot, chat_id, challenger_tg, DUEL_MUTE_MINUTES, ch_member)
        lines = [
            f"🤖 Бот отбился от {result['challenger_name']}.",
            f"Ставка {result['stake']} уходит в банк чата (теперь {result['bank_after']}).",
        ]
        if ok:
            lines.append(
                f"{result['challenger_name']} улетает в мут на {DUEL_MUTE_MINUTES} мин — только стикеры. 🤐"
            )
        else:
            logger.warning("duelbot: mute failed loser=%s: %s", challenger_tg, err)
            lines.append("(замутить не вышло — проверьте права бота.)")
    await msg.answer("\n".join(lines))
