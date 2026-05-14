"""Команды статистики чата и пользователя.

Дизайн:
- Текстовый вывод в моноспейс-блоке (HTML <pre>) — выравнивание сохраняется, мат/спецсимволы экранируются автоматически.
- Без ASCII-графиков (для визуальной аналитики используется LLM-команды /digest, /mood, /toxic).
- Аргумент N — число дней (1–365), по умолчанию 14.
- --chat <id> — для админов, чужой чат.
"""
import html
import re
from collections import Counter
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message as TgMessage
from sqlalchemy import distinct, func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.message import Message
from common.models.user import User

logger = get_logger(__name__)
router = Router()


# ---------------- args ----------------


def _parse_args(text: str, default_days: int = 14) -> tuple[int, int | None]:
    days = default_days
    chat_id = None
    parts = (text or "").split()[1:]
    if "--chat" in parts:
        i = parts.index("--chat")
        if i + 1 < len(parts):
            try:
                chat_id = int(parts[i + 1])
            except ValueError:
                pass
        parts = [p for j, p in enumerate(parts) if j not in (i, i + 1)]
    for p in parts:
        if re.fullmatch(r"\d{1,3}", p):
            days = max(1, min(365, int(p)))
            break
    return days, chat_id


async def _is_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def _check_chat_access(message: TgMessage, forced_chat_id: int | None) -> bool:
    if forced_chat_id is None or forced_chat_id == message.chat.id:
        return True
    if await _is_admin(message.bot, message.chat.id, message.from_user.id):
        return True
    await message.answer("Только для админов.")
    return False


def _since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _send_mono(message: TgMessage):
    async def _send(text: str):
        safe = html.escape(text)
        await message.answer(f"<pre>{safe}</pre>", parse_mode="HTML")
    return _send


# ---------------- text helpers ----------------


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{3,}")
_STOPWORDS = {
    # местоимения косвенных падежей и притяжательные
    "меня", "тебя", "нас", "вас", "них", "ему", "ней", "ним", "ими",
    "мне", "тебе", "нам", "вам", "им",
    "себя", "себе", "своим", "своей", "свою", "своё", "своих",
    "моей", "моим", "моих", "твоей", "твоим", "твоих",
    "нашей", "нашим", "наших", "вашей", "вашим", "ваших",
    # указательные
    "этот", "этого", "этому", "этом", "этим", "эта", "эту", "этой", "эти", "этих",
    "того", "тому", "тех", "той",
    "такой", "такая", "такое", "такие", "таким", "такого", "такому",
    # модальные/служебные
    "надо", "нужно", "можно", "нельзя", "должен", "должна", "должны",
    "хочу", "хочет", "хотел", "хотела", "хотим", "хотят", "хочется", "хотелось",
    "буду", "будет", "будем", "будут", "была", "было", "были", "быть",
    "может", "могут", "могла", "могли", "смог", "смогли",
    # частицы, связки, союзы
    "либо", "ибо", "чтобы", "чтоб", "потому", "поэтому", "пока",
    "если", "когда", "пусть", "хотя", "потом", "после", "перед",
    # притяжательные/субстантивы
    "который", "которая", "которые", "которое", "которых", "которому",
    "другой", "другая", "другое", "другие", "другому", "другим",
    # короткие распространённые
    "что", "как", "это", "так", "там", "тут", "туда", "сюда",
    "ещё", "уже", "тоже", "также", "просто", "только", "очень", "вообще", "значит",
    "вот", "вон", "ага", "угу", "ладно", "конечно", "наверное", "максимум",
    "блин", "типа", "короче", "кстати",
    # бытовые глаголы первого/третьего лица в фразах
    "знаю", "знает", "знал", "знала", "знаешь", "знают", "знаем",
    "думаю", "думает", "думал", "думала", "думаешь", "думают", "думаем",
    "делаю", "делает", "делал", "делала", "делают", "делаем",
    "сказал", "сказала", "сказали", "говорит", "говорил", "говорила",
    "смотри", "смотрит", "смотрел", "смотрите", "смотрят",
    # дни
    "вчера", "сегодня", "завтра", "раньше", "часто", "редко",
    "всегда", "никогда", "иногда",
    # английские частые
    "from", "with", "this", "that", "what", "they", "them", "have", "been", "were",
    "will", "just", "like", "yeah", "okay", "really", "would", "could", "should",
    "about", "there", "where", "which", "your", "their",
}


def _top_words(texts: list[str], limit: int = 5) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for t in texts:
        if not t:
            continue
        for w in _WORD_RE.findall(t.lower()):
            if w in _STOPWORDS:
                continue
            c[w] += 1
    return c.most_common(limit)


def _author_name(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.fullname:
        return user.fullname
    return "Unknown"


def _names_map(session, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = session.query(User).filter(User.id.in_(user_ids)).all()
    return {u.id: _author_name(u) for u in rows}


def _peak_hour(session, chat_id: int, since: datetime, user_db_id: int | None = None) -> int | None:
    q = session.query(
        func.extract("hour", Message.created_at).label("h"),
        func.count(Message.id),
    ).filter(
        Message.chat_id == chat_id,
        Message.created_at >= since,
    )
    if user_db_id is not None:
        q = q.filter(Message.user_id == user_db_id)
    row = q.group_by("h").order_by(func.count(Message.id).desc()).limit(1).first()
    return int(row[0]) if row else None


# ---------------- /mystats ----------------


@router.message(Command("mystats"))
async def cmd_mystats(message: TgMessage):
    send = _send_mono(message)
    session = SessionLocal()
    try:
        days, forced_chat = _parse_args(message.text or "")
        if not await _check_chat_access(message, forced_chat):
            return
        chat_id = forced_chat or message.chat.id
        tg_user = message.from_user

        user = session.query(User).filter(User.tg_id == tg_user.id).first()
        if not user:
            user = User(tg_id=tg_user.id, username=tg_user.username, fullname=tg_user.full_name)
            session.add(user)
            session.commit()
            session.refresh(user)

        since = _since(days)

        msg_count = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id, Message.user_id == user.id, Message.created_at >= since,
        ).scalar() or 0

        if msg_count == 0:
            await send(f"{_author_name(user)} · {days} дн.\n\nНет сообщений за период.")
            return

        total_chat = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
        ).scalar() or 1

        active_days = session.query(func.count(distinct(func.date_trunc("day", Message.created_at)))).filter(
            Message.chat_id == chat_id, Message.user_id == user.id, Message.created_at >= since,
        ).scalar() or 0

        avg_len_raw = session.query(func.avg(func.length(Message.text))).filter(
            Message.chat_id == chat_id, Message.user_id == user.id, Message.created_at >= since,
            Message.text.isnot(None), Message.text != "",
        ).scalar()
        avg_len = int(avg_len_raw or 0)

        replies_made = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id, Message.user_id == user.id,
            Message.created_at >= since, Message.reply_to.isnot(None),
        ).scalar() or 0

        # Сколько раз ответили на сообщения этого пользователя.
        my_tg_ids = session.query(Message.message_id).filter(
            Message.chat_id == chat_id, Message.user_id == user.id,
        ).subquery()
        replies_received = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id,
            Message.created_at >= since,
            Message.reply_to.in_(my_tg_ids),
        ).scalar() or 0

        # Место в чате.
        ranks = (
            session.query(Message.user_id, func.count(Message.id).label("c"))
            .filter(Message.chat_id == chat_id, Message.created_at >= since)
            .group_by(Message.user_id)
            .order_by(func.count(Message.id).desc())
            .all()
        )
        rank = next((i + 1 for i, (uid, _) in enumerate(ranks) if uid == user.id), None)

        peak = _peak_hour(session, chat_id, since, user.id)
        peak_str = f"~{peak:02d}:00" if peak is not None else "—"

        texts = [t[0] for t in session.query(Message.text).filter(
            Message.chat_id == chat_id, Message.user_id == user.id, Message.created_at >= since,
            Message.text.isnot(None),
        ).all()]
        top = _top_words(texts, limit=1)
        fav = f"«{top[0][0]}» (×{top[0][1]})" if top else "—"

        share = msg_count / total_chat * 100
        rank_str = f"место #{rank}" if rank else "—"

        lines = [
            f"{_author_name(user)} · {days} дн.",
            "",
            f"Сообщений: {msg_count} ({share:.1f}% чата, {rank_str})",
            f"Ср. длина: {avg_len} · пик ~{peak_str} · активных дней: {active_days}",
            f"Ответил: {replies_made} · получил ответов: {replies_received}",
            f"Любимое слово: {fav}",
        ]
        await send("\n".join(lines))
    except Exception as exc:
        logger.exception("mystats failed")
        await message.answer(f"Ошибка: {exc}")
    finally:
        session.close()


# ---------------- /chatstats ----------------


@router.message(Command("chatstats"))
async def cmd_chatstats(message: TgMessage):
    send = _send_mono(message)
    session = SessionLocal()
    try:
        days, forced_chat = _parse_args(message.text or "")
        if not await _check_chat_access(message, forced_chat):
            return
        chat_id = forced_chat or message.chat.id
        since = _since(days)

        total = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
        ).scalar() or 0

        if total == 0:
            await send(f"Чат · {days} дн.\n\nНет сообщений за период.")
            return

        active_users = session.query(func.count(distinct(Message.user_id))).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
        ).scalar() or 0

        replies = session.query(func.count(Message.id)).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
            Message.reply_to.isnot(None),
        ).scalar() or 0
        reply_rate = replies / total * 100

        # Самый активный день.
        busy_row = (
            session.query(func.date_trunc("day", Message.created_at).label("d"), func.count(Message.id).label("c"))
            .filter(Message.chat_id == chat_id, Message.created_at >= since)
            .group_by("d").order_by(func.count(Message.id).desc()).limit(1).first()
        )
        busy_str = f"{busy_row[0].strftime('%d %b').lower()} ({int(busy_row[1])})" if busy_row else "—"

        # Топ-5 авторов.
        top_rows = (
            session.query(Message.user_id, func.count(Message.id).label("c"))
            .filter(Message.chat_id == chat_id, Message.created_at >= since)
            .group_by(Message.user_id)
            .order_by(func.count(Message.id).desc())
            .limit(5).all()
        )
        names = _names_map(session, [r[0] for r in top_rows])
        max_name_len = max((len(names.get(uid, str(uid))) for uid, _ in top_rows), default=0)

        # Топ слов.
        texts = [t[0] for t in session.query(Message.text).filter(
            Message.chat_id == chat_id, Message.created_at >= since, Message.text.isnot(None),
        ).all()]
        top_words = _top_words(texts, limit=8)
        words_str = ", ".join(f"{w}×{c}" for w, c in top_words) if top_words else "—"

        lines = [
            f"Чат · {days} дн.",
            "",
            f"Сообщений: {total} · активных: {active_users} · пик-день: {busy_str}",
            f"Ответы: {reply_rate:.0f}% от всех сообщений",
            "",
            "Топ авторов:",
        ]
        for i, (uid, cnt) in enumerate(top_rows, 1):
            share = cnt / total * 100
            name = names.get(uid, str(uid))
            lines.append(f"  {i}. {name:<{max_name_len}}  {cnt:>5}  ({share:.0f}%)")
        lines.append("")
        lines.append(f"Топ слов: {words_str}")

        await send("\n".join(lines))
    except Exception as exc:
        logger.exception("chatstats failed")
        await message.answer(f"Ошибка: {exc}")
    finally:
        session.close()


# ---------------- /who ----------------


@router.message(Command("who"))
async def cmd_who(message: TgMessage):
    send = _send_mono(message)
    session = SessionLocal()
    try:
        days, forced_chat = _parse_args(message.text or "")
        if not await _check_chat_access(message, forced_chat):
            return
        chat_id = forced_chat or message.chat.id
        since = _since(days)

        rows = (
            session.query(Message.user_id, func.count(Message.id).label("c"))
            .filter(Message.chat_id == chat_id, Message.created_at >= since)
            .group_by(Message.user_id)
            .order_by(func.count(Message.id).desc())
            .all()
        )
        if not rows:
            await send(f"Активные за {days} дн.\n\nНикого нет.")
            return

        user_ids = [r[0] for r in rows]
        names = _names_map(session, user_ids)

        # Пиковый час каждому.
        peak_rows = session.query(
            Message.user_id,
            func.extract("hour", Message.created_at).label("h"),
            func.count(Message.id).label("c"),
        ).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
        ).group_by(Message.user_id, "h").all()
        peak_by_user: dict[int, tuple[int, int]] = {}
        for uid, h, c in peak_rows:
            cur = peak_by_user.get(uid)
            if cur is None or c > cur[1]:
                peak_by_user[uid] = (int(h), int(c))

        # Топ-слово каждому.
        texts_by_user: dict[int, list[str]] = {}
        text_rows = session.query(Message.user_id, Message.text).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
            Message.text.isnot(None), Message.text != "",
        ).all()
        for uid, t in text_rows:
            texts_by_user.setdefault(uid, []).append(t)

        max_name_len = max((len(names.get(uid, str(uid))) for uid in user_ids), default=10)
        max_count_len = max((len(str(c)) for _, c in rows), default=4)

        lines = [f"Активные за {days} дн.", ""]
        for i, (uid, cnt) in enumerate(rows, 1):
            name = names.get(uid, str(uid))
            peak = peak_by_user.get(uid)
            peak_str = f"~{peak[0]:02d}:00" if peak else "—   "
            top = _top_words(texts_by_user.get(uid, []), limit=1)
            fav = f"«{top[0][0]}»" if top else "—"
            lines.append(f"{i:>2}. {name:<{max_name_len}}  {cnt:>{max_count_len}}  пик {peak_str}  {fav}")

        await send("\n".join(lines))
    except Exception as exc:
        logger.exception("who failed")
        await message.answer(f"Ошибка: {exc}")
    finally:
        session.close()


# ---------------- /peakday ----------------


@router.message(Command("peakday"))
async def cmd_peakday(message: TgMessage):
    send = _send_mono(message)
    session = SessionLocal()
    try:
        days, forced_chat = _parse_args(message.text or "")
        if not await _check_chat_access(message, forced_chat):
            return
        chat_id = forced_chat or message.chat.id
        since = _since(days)

        rows = (
            session.query(func.date_trunc("day", Message.created_at).label("d"), func.count(Message.id).label("c"))
            .filter(Message.chat_id == chat_id, Message.created_at >= since)
            .group_by("d").order_by(func.count(Message.id).desc())
            .limit(3).all()
        )
        if not rows:
            await send(f"Пиковые дни за {days} дн.\n\nНет данных.")
            return

        lines = [f"Пиковые дни за {days} дн.", ""]
        for i, (day_dt, cnt) in enumerate(rows, 1):
            day_start = day_dt
            day_end = day_dt + timedelta(days=1)
            texts = [t[0] for t in session.query(Message.text).filter(
                Message.chat_id == chat_id,
                Message.created_at >= day_start,
                Message.created_at < day_end,
                Message.text.isnot(None),
            ).all()]
            top = _top_words(texts, limit=5)
            words = ", ".join(w for w, _ in top) if top else "—"
            lines.append(f"{i}. {day_start.strftime('%d %b').lower()} — {int(cnt)} сообщ.")
            lines.append(f"   топ слов: {words}")

        await send("\n".join(lines))
    except Exception as exc:
        logger.exception("peakday failed")
        await message.answer(f"Ошибка: {exc}")
    finally:
        session.close()


# ---------------- /streak ----------------


@router.message(Command("streak"))
async def cmd_streak(message: TgMessage):
    send = _send_mono(message)
    session = SessionLocal()
    try:
        days, forced_chat = _parse_args(message.text or "")
        if not await _check_chat_access(message, forced_chat):
            return
        chat_id = forced_chat or message.chat.id
        since = _since(days)

        rows = session.query(
            Message.user_id,
            func.date(Message.created_at).label("d"),
        ).filter(
            Message.chat_id == chat_id, Message.created_at >= since,
        ).group_by(Message.user_id, "d").all()

        by_user: dict[int, set] = {}
        for uid, d in rows:
            by_user.setdefault(uid, set()).add(d)

        if not by_user:
            await send(f"Стрики активности за {days} дн.\n\nНет данных.")
            return

        results: list[tuple[int, int, object]] = []  # (user_id, max_streak, last_day_of_streak)
        for uid, dates in by_user.items():
            sorted_dates = sorted(dates)
            max_s = cur = 1
            cur_end = sorted_dates[0]
            best_end = cur_end
            for prev, cur_d in zip(sorted_dates, sorted_dates[1:]):
                if (cur_d - prev).days == 1:
                    cur += 1
                    cur_end = cur_d
                    if cur > max_s:
                        max_s = cur
                        best_end = cur_end
                else:
                    cur = 1
                    cur_end = cur_d
            results.append((uid, max_s, best_end))

        results.sort(key=lambda x: -x[1])
        names = _names_map(session, [r[0] for r in results])

        max_name_len = max((len(names.get(uid, str(uid))) for uid, _, _ in results), default=10)

        lines = [f"Стрики активности за {days} дн.", ""]
        for i, (uid, streak, last_day) in enumerate(results[:15], 1):
            name = names.get(uid, str(uid))
            lines.append(f"{i:>2}. {name:<{max_name_len}}  {streak} дн.  (последний: {last_day.strftime('%d %b').lower()})")

        await send("\n".join(lines))
    except Exception as exc:
        logger.exception("streak failed")
        await message.answer(f"Ошибка: {exc}")
    finally:
        session.close()


# ---------------- /help ----------------


HELP_TEXT = """Команды бота

[Статистика]
  /mystats [N]       твоя стата за N дней (по умолч. 14)
  /chatstats [N]     стата чата
  /who [N]           список активных, по строке на человека
  /peakday [N]       топ-3 самых активных дня
  /streak [N]        стрики активности подряд

[AI и пересказы]
  /summary [N]              пересказ N последних сообщений
  /summary_custom N | фокус кастомный пересказ
  /digest [N]               дайджест чата (с детекцией всплесков)
  /digest 7 --debug         debug-промпт без LLM-вызова
  /card [@user]             карточка участника
  /mood [N]                 настроение чата
  /toxic [N]                токсичность чата
  /topics [N]               кластеризация чата по темам
  /ask <вопрос>             поиск ответа в истории чата (RAG)

[Игровое]
  /fag       случайный участник дня
  /joke      анекдот дня
  /phrase    фраза дня в стиле чата

[Экономика]
  /balance              твой баланс коинов (стартовый бонус 1000)
  /leaderboard          топ балансов чата
  /economy              общая экономика чата (банк, supply)
  /transfer @user N     перевод коинов

[Ставки]
  /casino                               открыть Mini App (UI для всего ниже)
  /market_create q | opt1 | opt2 | 7d   создать рынок (комиссия 100)
  /markets [open|closed|resolved|all]   список рынков
  /market <id>                          карточка рынка
  /bet <id> <opt> <amount>              поставить
  /portfolio                            мои ставки
  /market_import <url>                  импорт из polymarket/manifold (комиссия 50)

[Админ]
  /prompt_show, /prompt_set, /prompt_reset
  /model_show, /model_list, /model_set
  /admin_status                    полное состояние бота
  /backfill list|start|stop        управление backfill
  /admin_adjust @user ±N [note]    ручная корректировка баланса
  /market_resolve <id> <winner_idx> закрыть рынок и выплатить
  /market_cancel <id>              отменить рынок с возвратом всех ставок

Аргументы:
  N — число дней (1–365, по умолч. 14)
  --chat <id> — другой чат (только для админов)"""


@router.message(Command("help"))
async def cmd_help(message: TgMessage):
    safe = html.escape(HELP_TEXT)
    await message.answer(f"<pre>{safe}</pre>", parse_mode="HTML")
