from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message as TgMessage
from datetime import datetime, timedelta
from sqlalchemy import func, and_
from sqlalchemy.orm import aliased

import re
from collections import Counter

from common.db.db import SessionLocal
from common.models.user import User
from common.models.message import Message
from common.logger.logger import get_logger

logger = get_logger(__name__)
router = Router()


# -----------------------------
# helpers: parsing args
# -----------------------------
def _parse_days_and_chat(text: str):
    """
    /mystats 14 --chat -100123
    /mystats --chat -100123 30
    /mystats 7
    """
    days = 14
    chat_id = None

    parts = (text or "").split()
    # parts[0] = command
    tail = parts[1:]

    # find --chat
    if "--chat" in tail:
        i = tail.index("--chat")
        if i + 1 < len(tail):
            try:
                chat_id = int(tail[i + 1])
            except:
                chat_id = None
        # remove them for days parsing
        new_tail = []
        skip = set([i, i + 1])
        for idx, p in enumerate(tail):
            if idx in skip:
                continue
            new_tail.append(p)
        tail = new_tail

    # parse days from remaining numeric token
    for p in tail:
        if re.fullmatch(r"\d{1,4}", p):
            days = max(1, min(3650, int(p)))
            break

    return days, chat_id


async def _is_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False


# -----------------------------
# helpers: activity sparkline
# -----------------------------
_BLOCKS = "▁▂▃▄▅▆▇█"

def _sparkline(values):
    if not values:
        return "—"
    mx = max(values)
    if mx <= 0:
        return "—"
    res = []
    for v in values:
        idx = int(round((v / mx) * (len(_BLOCKS) - 1)))
        idx = max(0, min(len(_BLOCKS) - 1, idx))
        res.append(_BLOCKS[idx])
    return "".join(res)


# -----------------------------
# helpers: text analysis
# -----------------------------
_RU_STOPWORDS = {
    # местоимения / союзы / предлоги / частицы / “мусор”
    "я","ты","он","она","оно","мы","вы","они","меня","тебя","его","ее","её","нас","вас","их",
    "мне","тебе","ему","ей","нам","вам","им","мой","твой","наш","ваш","свой","сам","сама","сами",
    "это","этот","эта","эти","тот","та","те","там","тут","здесь","куда","откуда","где","когда","почему","зачем","как",
    "и","а","но","или","либо","да","нет","же","бы","б","вот","ну","ок","ага",
    "в","во","на","по","к","ко","у","о","об","от","до","из","за","для","про","при","без","над","под","между",
    "что","чтобы","чтоб","если","то","так","тоже","также","ещё","еще","уже","все","всё","вся","всех","всем",
    "там","тут","сюда","отсюда","сюда","тогда","сейчас","сегодня","вчера","завтра",
    "просто","типа","короче","вообще","реально","буквально",
}

_WORD_RE = re.compile(r"[a-zа-яё0-9']+", re.IGNORECASE)

def _top_words(texts, limit=5):
    c = Counter()
    for t in texts:
        if not t:
            continue
        t = t.lower()
        for w in _WORD_RE.findall(t):
            if len(w) < 3:
                continue
            if w in _RU_STOPWORDS:
                continue
            c[w] += 1
    return c.most_common(limit)


# -----------------------------
# DB stats pieces
# -----------------------------
def _since(days: int):
    return datetime.utcnow() - timedelta(days=days)


def _get_or_create_user(session, tg_user) -> User:
    user = session.query(User).filter_by(tg_id=tg_user.id).first()
    if not user:
        user = User(tg_id=tg_user.id, username=tg_user.username, fullname=tg_user.full_name)
        session.add(user)
        session.flush()
    return user


def _count_replies_made(session, chat_id: int, user_db_id: int, since_dt):
    ReplyTo = aliased(Message)
    q = (
        session.query(func.count(Message.id))
        .join(
            ReplyTo,
            and_(
                Message.chat_id == ReplyTo.chat_id,
                Message.reply_to == ReplyTo.telegram_message_id,
            )
        )
        .filter(
            Message.chat_id == chat_id,
            Message.user_id == user_db_id,
            Message.created_at >= since_dt,
            ReplyTo.user_id != user_db_id,
        )
    )
    return q.scalar() or 0


def _count_replies_received(session, chat_id: int, user_db_id: int, since_dt):
    Answer = aliased(Message)
    Original = aliased(Message)
    q = (
        session.query(func.count(Answer.id))
        .join(
            Original,
            and_(
                Answer.chat_id == Original.chat_id,
                Answer.reply_to == Original.telegram_message_id,
            )
        )
        .filter(
            Answer.chat_id == chat_id,
            Answer.created_at >= since_dt,
            Original.user_id == user_db_id,
            Answer.user_id != user_db_id,
        )
    )
    return q.scalar() or 0


def _activity_by_day(session, chat_id: int, user_db_id: int, since_dt, days: int):
    # Postgres: date_trunc('day', created_at)
    rows = (
        session.query(func.date_trunc("day", Message.created_at).label("d"), func.count(Message.id))
        .filter(
            Message.chat_id == chat_id,
            Message.user_id == user_db_id,
            Message.created_at >= since_dt,
        )
        .group_by("d")
        .order_by("d")
        .all()
    )
    m = {r[0].date(): int(r[1]) for r in rows}

    # full series day-by-day
    start = (datetime.utcnow() - timedelta(days=days-1)).date()
    series = []
    labels = []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d)
        series.append(m.get(d, 0))
    return labels, series


def _peak_hour(session, chat_id: int, user_db_id: int, since_dt):
    # extract hour (0-23)
    rows = (
        session.query(func.extract("hour", Message.created_at).label("h"), func.count(Message.id))
        .filter(
            Message.chat_id == chat_id,
            Message.user_id == user_db_id,
            Message.created_at >= since_dt,
        )
        .group_by("h")
        .order_by(func.count(Message.id).desc())
        .limit(1)
        .all()
    )
    if not rows:
        return None
    return int(rows[0][0])

def _chat_peak_hour(session, chat_id: int, since_dt):
    rows = (
        session.query(func.extract("hour", Message.created_at).label("h"), func.count(Message.id))
        .filter(Message.chat_id == chat_id, Message.created_at >= since_dt)
        .group_by("h")
        .order_by(func.count(Message.id).desc())
        .limit(1)
        .all()
    )
    if not rows:
        return None
    return int(rows[0][0])


def _chat_busiest_day(session, chat_id: int, since_dt):
    rows = (
        session.query(func.date_trunc("day", Message.created_at).label("d"), func.count(Message.id).label("c"))
        .filter(Message.chat_id == chat_id, Message.created_at >= since_dt)
        .group_by("d")
        .order_by(func.count(Message.id).desc())
        .limit(1)
        .all()
    )
    if not rows:
        return None, 0
    return rows[0][0].date(), int(rows[0][1])


def _reply_edges(session, chat_id: int, since_dt, limit: int = 30):
    """
    Граф связей: Answer.user_id -> Original.user_id, вес = кол-во reply.
    """
    Answer = aliased(Message)
    Original = aliased(Message)

    rows = (
        session.query(
            Answer.user_id.label("src"),
            Original.user_id.label("dst"),
            func.count(Answer.id).label("c"),
        )
        .join(
            Original,
            and_(
                Answer.chat_id == Original.chat_id,
                Answer.reply_to == Original.telegram_message_id,
            )
        )
        .filter(
            Answer.chat_id == chat_id,
            Answer.created_at >= since_dt,
            Answer.user_id.isnot(None),
            Original.user_id.isnot(None),
            Answer.user_id != Original.user_id,
        )
        .group_by(Answer.user_id, Original.user_id)
        .order_by(func.count(Answer.id).desc())
        .limit(limit)
        .all()
    )
    return [(int(r[0]), int(r[1]), int(r[2])) for r in rows]


def _reply_in_out(session, chat_id: int, since_dt):
    """
    out: сколько reply написал пользователь (кому угодно)
    in: сколько reply получили сообщения пользователя (от кого угодно)
    """
    Answer = aliased(Message)
    Original = aliased(Message)

    out_rows = (
        session.query(Answer.user_id, func.count(Answer.id).label("c"))
        .join(
            Original,
            and_(
                Answer.chat_id == Original.chat_id,
                Answer.reply_to == Original.telegram_message_id,
            )
        )
        .filter(
            Answer.chat_id == chat_id,
            Answer.created_at >= since_dt,
            Answer.user_id.isnot(None),
            Original.user_id.isnot(None),
            Answer.user_id != Original.user_id,
        )
        .group_by(Answer.user_id)
        .order_by(func.count(Answer.id).desc())
        .all()
    )

    in_rows = (
        session.query(Original.user_id, func.count(Answer.id).label("c"))
        .join(
            Answer,
            and_(
                Answer.chat_id == Original.chat_id,
                Answer.reply_to == Original.telegram_message_id,
            )
        )
        .filter(
            Answer.chat_id == chat_id,
            Answer.created_at >= since_dt,
            Answer.user_id.isnot(None),
            Original.user_id.isnot(None),
            Answer.user_id != Original.user_id,
        )
        .group_by(Original.user_id)
        .order_by(func.count(Answer.id).desc())
        .all()
    )

    out_map = {int(uid): int(c) for uid, c in out_rows}
    in_map = {int(uid): int(c) for uid, c in in_rows}
    return out_map, in_map


def _names_map(session, user_ids):
    if not user_ids:
        return {}
    users = session.query(User).filter(User.id.in_(list(set(user_ids)))).all()
    return {u.id: (u.fullname or u.username or str(u.tg_id)) for u in users}

def _calc_user_stats_text(session, chat_id: int, user: User, days: int) -> str:
    since_dt = _since(days)

    msgs_q = (
        session.query(Message)
        .filter(
            Message.chat_id == chat_id,
            Message.user_id == user.id,
            Message.created_at >= since_dt,
        )
        .order_by(Message.created_at.desc())
    )

    msg_count = msgs_q.count()

    texts = [t[0] for t in session.query(Message.text).filter(
        Message.chat_id == chat_id,
        Message.user_id == user.id,
        Message.created_at >= since_dt,
        Message.text.isnot(None)
    ).all()]

    char_count = sum(len(t) for t in texts)
    word_count = sum(len(_WORD_RE.findall((t or "").lower())) for t in texts)
    avg_len = int(round(char_count / msg_count)) if msg_count else 0

    active_days = session.query(func.count(func.distinct(func.date_trunc("day", Message.created_at)))).filter(
        Message.chat_id == chat_id,
        Message.user_id == user.id,
        Message.created_at >= since_dt,
    ).scalar() or 0

    peak_hour = _peak_hour(session, chat_id, user.id, since_dt)

    labels, series = _activity_by_day(session, chat_id, user.id, since_dt, days)
    spark = _sparkline(series)
    top = _top_words(texts, limit=5)

    replies_made = _count_replies_made(session, chat_id, user.id, since_dt)
    replies_received = _count_replies_received(session, chat_id, user.id, since_dt)

    # “любимое слово”
    fav_word = top[0][0] if top else "—"
    fav_word_cnt = top[0][1] if top else 0

    top_words_str = "—" if not top else ", ".join([f"{w}×{c}" for w, c in top])

    name = user.fullname or user.username or str(user.tg_id)

    lines = []
    lines.append(f"📊 Статистика за {days} дн. по чату `{chat_id}`")
    lines.append(f"👤 {name}")
    lines.append("")
    lines.append(f"💬 Сообщений: {msg_count}")
    lines.append(f"🗓 Активных дней: {active_days}")
    lines.append(f"⌨️ Символов: {char_count} · слов: {word_count} · ср. длина: {avg_len}")
    if peak_hour is not None:
        lines.append(f"🕒 Пиковый час: ~{peak_hour:02d}:00")
    lines.append("")
    lines.append(f"📈 Активность по дням: {spark}")
    lines.append("")
    lines.append(f"🧠 Любимое слово: **{fav_word}** (×{fav_word_cnt})")
    lines.append(f"🔤 Топ слов: {top_words_str}")
    lines.append("")
    lines.append(f"↩️ Ответил другим: {replies_made}")
    lines.append(f"💬 Ответили ему: {replies_received}")

    return "\n".join(lines)

def _calc_chat_stats_text(session, chat_id: int, days: int) -> str:
    since_dt = _since(days)

    total_msgs = session.query(func.count(Message.id)).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since_dt,
    ).scalar() or 0

    active_users = session.query(func.count(func.distinct(Message.user_id))).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since_dt,
    ).scalar() or 0

    active_days = session.query(func.count(func.distinct(func.date_trunc("day", Message.created_at)))).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since_dt,
    ).scalar() or 0

    # reply rate
    reply_msgs = session.query(func.count(Message.id)).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since_dt,
        Message.reply_to.isnot(None),
    ).scalar() or 0
    reply_rate = (reply_msgs / total_msgs * 100.0) if total_msgs else 0.0

    # топ пользователей по сообщениям
    top_rows = (
        session.query(Message.user_id, func.count(Message.id).label("c"))
        .filter(Message.chat_id == chat_id, Message.created_at >= since_dt)
        .group_by(Message.user_id)
        .order_by(func.count(Message.id).desc())
        .limit(10)
        .all()
    )
    user_ids_top = [r[0] for r in top_rows]
    umap = _names_map(session, user_ids_top)

    top_lines = []
    for i, (uid, c) in enumerate(top_rows, start=1):
        top_lines.append(f"{i}. {umap.get(uid, str(uid))} — {c}")

    # общая активность по дням
    rows = (
        session.query(func.date_trunc("day", Message.created_at).label("d"), func.count(Message.id))
        .filter(Message.chat_id == chat_id, Message.created_at >= since_dt)
        .group_by("d")
        .order_by("d")
        .all()
    )
    m = {r[0].date(): int(r[1]) for r in rows}
    start = (datetime.utcnow() - timedelta(days=days-1)).date()
    series = [m.get(start + timedelta(days=i), 0) for i in range(days)]
    spark = _sparkline(series)

    # кто кому отвечает (граф)
    edges = _reply_edges(session, chat_id, since_dt, limit=10)
    edge_ids = []
    for a, b, _ in edges:
        edge_ids.extend([a, b])
    nmap = _names_map(session, edge_ids)

    edges_lines = []
    for i, (a, b, c) in enumerate(edges, start=1):
        edges_lines.append(f"{i}. {nmap.get(a, a)} → {nmap.get(b, b)} — {c}")

    out_map, in_map = _reply_in_out(session, chat_id, since_dt)
    # топ 5 кто больше отвечает
    top_out = sorted(out_map.items(), key=lambda x: x[1], reverse=True)[:5]
    top_in = sorted(in_map.items(), key=lambda x: x[1], reverse=True)[:5]
    out_names = _names_map(session, [u for u, _ in top_out])
    in_names = _names_map(session, [u for u, _ in top_in])

    top_out_lines = [f"{i}. {out_names.get(u, u)} — {c}" for i, (u, c) in enumerate(top_out, 1)]
    top_in_lines = [f"{i}. {in_names.get(u, u)} — {c}" for i, (u, c) in enumerate(top_in, 1)]

    # пиковые показатели
    peak_hour = _chat_peak_hour(session, chat_id, since_dt)
    busy_day, busy_cnt = _chat_busiest_day(session, chat_id, since_dt)

    # топ слов по чату
    texts = [t[0] for t in session.query(Message.text).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since_dt,
        Message.text.isnot(None)
    ).all()]
    top_words = _top_words(texts, limit=7)
    top_words_str = "—" if not top_words else ", ".join([f"{w}×{c}" for w, c in top_words])

    lines = []
    lines.append(f"📊 Статистика чата `{chat_id}` за {days} дн.")
    lines.append("")
    lines.append(f"💬 Сообщений: {total_msgs}")
    lines.append(f"👥 Активных пользователей: {active_users}")
    lines.append(f"🗓 Активных дней: {active_days}")
    lines.append(f"↩️ Сообщений-ответов: {reply_msgs} ({reply_rate:.1f}%)")
    if peak_hour is not None:
        lines.append(f"🕒 Пиковый час чата: ~{peak_hour:02d}:00")
    if busy_day is not None:
        lines.append(f"🔥 Самый активный день: {busy_day.isoformat()} — {busy_cnt}")
    lines.append("")
    lines.append(f"📈 Активность по дням: {spark}")
    lines.append("")
    lines.append("🏆 Топ по сообщениям:")
    lines.append("\n".join(top_lines) if top_lines else "—")
    lines.append("")
    lines.append("🧠 Топ слов по чату:")
    lines.append(top_words_str)
    lines.append("")
    lines.append("💬 Кто больше всех отвечает (reply-out):")
    lines.append("\n".join(top_out_lines) if top_out_lines else "—")
    lines.append("")
    lines.append("🎯 Кому чаще всего отвечают (reply-in):")
    lines.append("\n".join(top_in_lines) if top_in_lines else "—")
    lines.append("")
    lines.append("🕸 Топ связей A → B:")
    lines.append("\n".join(edges_lines) if edges_lines else "—")

    return "\n".join(lines)



# -----------------------------
# commands
# -----------------------------
@router.message(Command("mystats"))
async def cmd_mystats(message: TgMessage):
    session = SessionLocal()
    try:
        days, forced_chat_id = _parse_days_and_chat(message.text or "")
        chat_id = forced_chat_id or message.chat.id

        # запрет “смотреть другой чат” не-админам
        if forced_chat_id is not None and forced_chat_id != message.chat.id:
            is_admin = await _is_admin(message.bot, message.chat.id, message.from_user.id)
            if not is_admin:
                await message.answer("⛔️ Смотреть статистику другого чата можно только админам текущего чата.")
                return

        user = _get_or_create_user(session, message.from_user)

        text = _calc_user_stats_text(session, chat_id=chat_id, user=user, days=days)
        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"mystats error: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при расчёте статистики. Смотри логи.")
    finally:
        session.close()


@router.message(Command("chatstats"))
async def cmd_chatstats(message: TgMessage):
    session = SessionLocal()
    try:
        days, forced_chat_id = _parse_days_and_chat(message.text or "")
        chat_id = forced_chat_id or message.chat.id

        # chatstats по умолчанию — текущий чат; на другой чат тоже только админам
        if forced_chat_id is not None and forced_chat_id != message.chat.id:
            is_admin = await _is_admin(message.bot, message.chat.id, message.from_user.id)
            if not is_admin:
                await message.answer("⛔️ Смотреть статистику другого чата можно только админам текущего чата.")
                return

        text = _calc_chat_stats_text(session, chat_id=chat_id, days=days)
        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"chatstats error: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при расчёте статистики. Смотри логи.")
    finally:
        session.close()

@router.message(Command("chatgraph"))
async def cmd_chatgraph(message: TgMessage):
    session = SessionLocal()
    try:
        days, forced_chat_id = _parse_days_and_chat(message.text or "")
        chat_id = forced_chat_id or message.chat.id

        # смотреть другой чат — только админам текущего чата
        if forced_chat_id is not None and forced_chat_id != message.chat.id:
            is_admin = await _is_admin(message.bot, message.chat.id, message.from_user.id)
            if not is_admin:
                await message.answer("⛔️ Смотреть статистику другого чата можно только админам текущего чата.")
                return

        since_dt = _since(days)
        edges = _reply_edges(session, chat_id, since_dt, limit=30)
        if not edges:
            await message.answer("🕸 Граф связей пуст: нет reply (или оригиналы сообщений не залогированы).")
            return

        ids = []
        for a, b, _ in edges:
            ids.extend([a, b])
        nmap = _names_map(session, ids)

        # для каждого автора покажем его топ-цель
        best_to = {}
        for a, b, c in edges:
            if a not in best_to or c > best_to[a][1]:
                best_to[a] = (b, c)

        lines = []
        lines.append(f"🕸 Граф связей (reply) за {days} дн. · чат `{chat_id}`")
        lines.append("")
        lines.append("🏆 Топ рёбер (A → B):")
        for i, (a, b, c) in enumerate(edges[:15], start=1):
            lines.append(f"{i}. {nmap.get(a, a)} → {nmap.get(b, b)} — {c}")

        lines.append("")
        lines.append("🎯 Для каждого автора: кому он отвечает чаще всего:")
        items = sorted(best_to.items(), key=lambda x: x[1][1], reverse=True)[:15]
        for i, (a, (b, c)) in enumerate(items, start=1):
            lines.append(f"{i}. {nmap.get(a, a)} → {nmap.get(b, b)} — {c}")

        await message.answer("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"chatgraph error: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при построении графа. Смотри логи.")
    finally:
        session.close()

@router.message(Command("help"))
async def cmd_help(message: TgMessage):
    text = (
        "📊 *Помощь по статистике*\n\n"

        "👤 *Личная статистика*\n"
        "`/mystats` — твоя статистика в текущем чате\n"
        "`/mystats 30` — за последние 30 дней\n"
        "`/mystats 14 --chat -100123` — по другому чату (только для админов)\n\n"

        "💬 *Статистика чата*\n"
        "`/chatstats` — общая статистика текущего чата\n"
        "`/chatstats 30` — за 30 дней\n"
        "`/chatstats --chat -100123` — другой чат (только для админов)\n\n"

        "🕸 *Граф общения*\n"
        "`/chatgraph` — кто кому отвечает\n"
        "`/chatgraph 30` — за 30 дней\n\n"

        "⚙️ *Примечания*\n"
        "• Статистика строится только по сообщениям, которые видел бот\n"
        "• Ответы считаются по reply-сообщениям\n"
        "• Просмотр других чатов доступен только администраторам\n"
        "• Период по умолчанию — 14 дней\n\n"

        "ℹ️ Пример:\n"
        "`/mystats 7`\n"
        "`/chatstats 30`\n"
        "`/chatgraph`\n"
    )

    await message.answer(text, parse_mode="Markdown")
