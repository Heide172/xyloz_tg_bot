import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from common import prompts
from common.db.db import SessionLocal
from common.models.message import Message
from common.models.reaction import Reaction
from common.models.user import User
from services import ai_client
from services.summary_service import (
    MAX_CHARS_PER_MESSAGE,
    MAX_INPUT_TOKENS,
    _estimate_tokens,
    _truncate_text,
    get_summary_model,
)


DIGEST_MIN_DAYS = 1
DIGEST_MAX_DAYS = 30
DIGEST_DEFAULT_DAYS = 7

# Burst detection
BURST_TOP_K = 3
BURST_MIN_HOUR_COUNT = 8
BURST_MEDIAN_MULTIPLIER = 2.5
BURST_MAX_WIDTH_HOURS = 2  # окно шире — попробуем сузить до внутренних пиков
INNER_PEAK_SLOT_MIN = 10  # минутный слот
INNER_PEAK_TOP_K = 2
INNER_PEAK_CONTEXT_MIN = 3  # ±N минут вокруг пика

# Context for LLM
REPLY_CHAIN_TOP = 5
REPLY_CHAIN_MAX_REPLIES = 8
REPLY_CHAIN_MIN_REPLIES = 2
CHARACTERISTIC_WORDS_TOP = 12
BURST_SAMPLE_PER_WINDOW = 50
BACKGROUND_SAMPLE_LIMIT = 60
TOP_AUTHOR_LIMIT = 5

MSK = ZoneInfo("Europe/Moscow")

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{3,}")

# Минимальный стоп-список: только структурные слова. Мат и сленг оставляем — они характерны.
RU_STOP = {
    "это","этот","эта","эти","того","тому","тех","той","там","тут","туда","сюда",
    "вот","всё","все","всех","всем","всё","ещё","еще","уже","были","было","была","быть",
    "если","или","когда","который","которая","которые","которое","потом","тоже","также",
    "очень","можно","надо","нужно","будет","будут","будешь","нету","нет","нету","нету",
    "меня","тебя","нас","вас","них","ему","ей","ним","ней","мне","тебе","нам","вам","им",
    "себе","себя","свой","своя","свои","свою","моя","мой","мою","моё","твоя","твой","твою",
    "наш","наша","ваш","ваша","его","её","ее","их","который","которая","другой","другая",
    "просто","значит","вообще","может","быть","могу","могут","мог","могла","смог","смогли",
    "сейчас","сегодня","завтра","вчера","раньше","часто","всегда","никогда",
    "сказал","сказала","говорит","говорил","говорила",
    "хочу","хочет","хотел","хотела","хочется","хотелось",
    "делаю","делает","делал","делала","делаем","делают",
    "знаю","знает","знал","знала","знаешь","знаем","знают",
    "думаю","думает","думал","думала","думаешь","думаем","думают",
    "блин","ладно","кстати","короче","типа","ну","ага","угу","ну-ну",
    "from","with","this","that","what","they","them","were","have","been","will","just","like","yeah",
}


@dataclass
class RawMessage:
    db_id: int
    tg_message_id: int
    reply_to: int | None
    created_at: datetime
    author: str
    text: str
    reactions: int


@dataclass
class ReplyChain:
    root: RawMessage
    replies: list[RawMessage]


@dataclass
class BurstContext:
    start: datetime
    end: datetime
    count: int
    top_authors: list[tuple[str, int]]
    inner_peaks: list[tuple[datetime, datetime, int]]  # (slot_start, slot_end, count)
    characteristic_words: list[tuple[str, int, int]]  # (word, count_in_burst, count_in_background)
    reply_chains: list[ReplyChain]
    sample: list[RawMessage]


@dataclass
class DigestData:
    days: int
    period_start: datetime
    period_end: datetime
    total_messages: int
    active_users: int
    top_authors: list[tuple[str, int]]
    bursts: list[BurstContext]
    background_sample: list[RawMessage]
    background_total: int


def parse_digest_days(command_text: str, default: int = DIGEST_DEFAULT_DAYS) -> int:
    parts = (command_text or "").split()
    if len(parts) < 2:
        return default
    try:
        value = int(parts[1])
    except ValueError:
        raise ValueError("Дни должны быть числом, пример: /digest 7")
    if value < DIGEST_MIN_DAYS or value > DIGEST_MAX_DAYS:
        raise ValueError(f"Дни должны быть в диапазоне {DIGEST_MIN_DAYS}..{DIGEST_MAX_DAYS}")
    return value


def _author_label(username: str | None, fullname: str | None) -> str:
    if username:
        return f"@{username}"
    if fullname:
        return fullname
    return "Unknown"


def _to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def _fetch_period_messages(chat_id: int, days: int) -> tuple[list[RawMessage], datetime, datetime]:
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)

    session = SessionLocal()
    try:
        react_count = func.count(Reaction.id).label("react_count")
        rows = (
            session.query(
                Message.id,
                Message.telegram_message_id,
                Message.reply_to,
                Message.created_at,
                User.username,
                User.fullname,
                Message.text,
                react_count,
            )
            .outerjoin(User, Message.user_id == User.id)
            .outerjoin(Reaction, Reaction.message_id == Message.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .group_by(Message.id, User.username, User.fullname)
            .order_by(Message.created_at.asc())
            .all()
        )

        messages = [
            RawMessage(
                db_id=row.id,
                tg_message_id=row.telegram_message_id,
                reply_to=row.reply_to,
                created_at=row.created_at,
                author=_author_label(row.username, row.fullname),
                text=row.text.strip(),
                reactions=int(row.react_count or 0),
            )
            for row in rows
        ]
        return messages, period_start, period_end
    finally:
        session.close()


# ---------------- burst windows ----------------


def _find_hour_bursts(messages: list[RawMessage]) -> list[tuple[datetime, datetime]]:
    """Часовые бакеты, threshold, merge соседних."""
    if not messages:
        return []
    buckets: dict[datetime, int] = {}
    for m in messages:
        h = m.created_at.replace(minute=0, second=0, microsecond=0)
        buckets[h] = buckets.get(h, 0) + 1

    counts = sorted(buckets.values())
    median = counts[len(counts) // 2] if counts else 0
    threshold = max(BURST_MIN_HOUR_COUNT, int(median * BURST_MEDIAN_MULTIPLIER))

    hot = sorted(((h, c) for h, c in buckets.items() if c >= threshold), key=lambda x: x[0])
    if not hot:
        return []

    one_hour = timedelta(hours=1)
    merged: list[list] = []
    for h, c in hot:
        if merged and h == merged[-1][1]:
            merged[-1][1] = h + one_hour
            merged[-1][2] += c
        else:
            merged.append([h, h + one_hour, c])

    merged.sort(key=lambda w: -w[2])
    top = merged[:BURST_TOP_K]
    top.sort(key=lambda w: w[0])
    return [(w[0], w[1]) for w in top]


def _find_inner_peaks(in_window: list[RawMessage]) -> list[tuple[datetime, datetime, int]]:
    """Минутные пики плотности внутри окна. Возвращает (slot_start, slot_end, count)."""
    if not in_window:
        return []
    slot = timedelta(minutes=INNER_PEAK_SLOT_MIN)
    slots: dict[datetime, int] = {}
    for m in in_window:
        ts = m.created_at
        bucket_min = (ts.minute // INNER_PEAK_SLOT_MIN) * INNER_PEAK_SLOT_MIN
        key = ts.replace(minute=bucket_min, second=0, microsecond=0)
        slots[key] = slots.get(key, 0) + 1

    top = sorted(slots.items(), key=lambda x: -x[1])[:INNER_PEAK_TOP_K]
    top.sort(key=lambda x: x[0])
    return [(s, s + slot, c) for s, c in top]


def _maybe_narrow_burst(burst: tuple[datetime, datetime], in_window: list[RawMessage]) -> tuple[datetime, datetime]:
    """Если окно шире BURST_MAX_WIDTH_HOURS — сузить до объединения внутренних пиков ± контекст."""
    start, end = burst
    width = end - start
    if width <= timedelta(hours=BURST_MAX_WIDTH_HOURS):
        return burst
    peaks = _find_inner_peaks(in_window)
    if not peaks:
        return burst
    ctx = timedelta(minutes=INNER_PEAK_CONTEXT_MIN)
    new_start = min(p[0] for p in peaks) - ctx
    new_end = max(p[1] for p in peaks) + ctx
    # не выходим за изначальные границы
    new_start = max(new_start, start)
    new_end = min(new_end, end)
    if new_end - new_start < timedelta(minutes=INNER_PEAK_SLOT_MIN):
        return burst
    return (new_start, new_end)


# ---------------- reply chains ----------------


def _build_reply_chains(in_window: list[RawMessage]) -> list[ReplyChain]:
    """Топ root-сообщений по числу ответов внутри окна."""
    by_tg_id = {m.tg_message_id: m for m in in_window}
    reply_counts: Counter[int] = Counter()
    for m in in_window:
        if m.reply_to is not None and m.reply_to in by_tg_id:
            reply_counts[m.reply_to] += 1

    chains: list[ReplyChain] = []
    for root_tg_id, count in reply_counts.most_common(REPLY_CHAIN_TOP):
        if count < REPLY_CHAIN_MIN_REPLIES:
            break
        root = by_tg_id[root_tg_id]
        replies = sorted(
            (m for m in in_window if m.reply_to == root_tg_id),
            key=lambda x: x.created_at,
        )[:REPLY_CHAIN_MAX_REPLIES]
        chains.append(ReplyChain(root=root, replies=replies))
    return chains


# ---------------- characteristic words ----------------


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _word_counts(messages: list[RawMessage]) -> Counter[str]:
    c: Counter[str] = Counter()
    for m in messages:
        for w in _tokenize(m.text):
            if w in RU_STOP:
                continue
            c[w] += 1
    return c


def _characteristic_words(
    burst_msgs: list[RawMessage],
    background_msgs: list[RawMessage],
) -> list[tuple[str, int, int]]:
    if not burst_msgs:
        return []
    burst_c = _word_counts(burst_msgs)
    bg_c = _word_counts(background_msgs)

    # Скоринг: слова, частые в burst и редкие в фоне.
    # ratio = (burst_freq / burst_total + alpha) / (bg_freq / bg_total + alpha)
    burst_total = max(1, sum(burst_c.values()))
    bg_total = max(1, sum(bg_c.values()))
    alpha = 1.0 / (burst_total + bg_total)

    scored: list[tuple[str, float, int, int]] = []
    for word, cnt in burst_c.items():
        if cnt < 3:
            continue
        bf = burst_c.get(word, 0) / burst_total
        gf = bg_c.get(word, 0) / bg_total
        ratio = (bf + alpha) / (gf + alpha)
        scored.append((word, ratio, cnt, bg_c.get(word, 0)))
    scored.sort(key=lambda x: -x[1])
    return [(w, c, bgc) for w, _r, c, bgc in scored[:CHARACTERISTIC_WORDS_TOP]]


# ---------------- assemble burst context ----------------


def _build_burst_context(
    all_messages: list[RawMessage],
    window: tuple[datetime, datetime],
    background_msgs: list[RawMessage],
) -> BurstContext:
    start, end = window
    in_window = [m for m in all_messages if start <= m.created_at < end]
    if not in_window:
        return BurstContext(
            start=start, end=end, count=0, top_authors=[], inner_peaks=[],
            characteristic_words=[], reply_chains=[], sample=[],
        )

    # Сужаем если очень широкое
    new_window = _maybe_narrow_burst(window, in_window)
    if new_window != window:
        start, end = new_window
        in_window = [m for m in in_window if start <= m.created_at < end]

    author_counts = Counter(m.author for m in in_window)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)
    inner_peaks = _find_inner_peaks(in_window)
    char_words = _characteristic_words(in_window, background_msgs)
    chains = _build_reply_chains(in_window)

    # сэмпл: сначала тексты из цепочек, потом топ-по-реакциям, потом из пиков
    chain_msg_ids = {c.root.db_id for c in chains}
    for c in chains:
        chain_msg_ids.update(r.db_id for r in c.replies)

    by_reactions = sorted(in_window, key=lambda m: (-m.reactions, m.created_at))
    sample: list[RawMessage] = []
    seen_ids: set[int] = set()

    # сначала чейны (хронологически)
    chain_msgs = [m for m in in_window if m.db_id in chain_msg_ids]
    chain_msgs.sort(key=lambda m: m.created_at)
    for m in chain_msgs:
        if m.db_id not in seen_ids:
            sample.append(m)
            seen_ids.add(m.db_id)
            if len(sample) >= BURST_SAMPLE_PER_WINDOW:
                break

    # потом топ по реакциям
    if len(sample) < BURST_SAMPLE_PER_WINDOW:
        for m in by_reactions:
            if m.db_id in seen_ids:
                continue
            sample.append(m)
            seen_ids.add(m.db_id)
            if len(sample) >= BURST_SAMPLE_PER_WINDOW:
                break

    # если ещё есть место — добираем из inner peaks
    if len(sample) < BURST_SAMPLE_PER_WINDOW and inner_peaks:
        for s, e, _c in inner_peaks:
            for m in in_window:
                if not (s <= m.created_at < e):
                    continue
                if m.db_id in seen_ids:
                    continue
                sample.append(m)
                seen_ids.add(m.db_id)
                if len(sample) >= BURST_SAMPLE_PER_WINDOW:
                    break
            if len(sample) >= BURST_SAMPLE_PER_WINDOW:
                break

    sample.sort(key=lambda m: m.created_at)

    return BurstContext(
        start=start,
        end=end,
        count=len(in_window),
        top_authors=top_authors,
        inner_peaks=inner_peaks,
        characteristic_words=char_words,
        reply_chains=chains,
        sample=sample,
    )


def _build_background_sample(messages: list[RawMessage], burst_windows: list[tuple[datetime, datetime]]) -> tuple[list[RawMessage], int]:
    def in_any_burst(m: RawMessage) -> bool:
        for s, e in burst_windows:
            if s <= m.created_at < e:
                return True
        return False

    background = [m for m in messages if not in_any_burst(m)]
    total = len(background)
    if total <= BACKGROUND_SAMPLE_LIMIT:
        return background, total

    step = total / BACKGROUND_SAMPLE_LIMIT
    sampled = [background[min(int(i * step), total - 1)] for i in range(BACKGROUND_SAMPLE_LIMIT)]
    sampled.sort(key=lambda m: m.created_at)
    return sampled, total


def _build_digest_data(messages: list[RawMessage], period_start: datetime, period_end: datetime, days: int) -> DigestData:
    author_counts = Counter(m.author for m in messages)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)
    active_users = len(author_counts)

    initial_windows = _find_hour_bursts(messages)

    # Первый проход: формируем background, исключая полные часовые окна (до сужения)
    bg_msgs_initial = []
    for m in messages:
        skip = False
        for s, e in initial_windows:
            if s <= m.created_at < e:
                skip = True
                break
        if not skip:
            bg_msgs_initial.append(m)

    # Строим burst-контексты (с возможным сужением окна)
    bursts: list[BurstContext] = []
    for w in initial_windows:
        ctx = _build_burst_context(messages, w, bg_msgs_initial)
        if ctx.count > 0:
            bursts.append(ctx)

    final_windows = [(b.start, b.end) for b in bursts]
    background, background_total = _build_background_sample(messages, final_windows)

    return DigestData(
        days=days,
        period_start=period_start,
        period_end=period_end,
        total_messages=len(messages),
        active_users=active_users,
        top_authors=top_authors,
        bursts=bursts,
        background_sample=background,
        background_total=background_total,
    )


# ---------------- prompt building ----------------


def _clip(text: str, limit: int = MAX_CHARS_PER_MESSAGE) -> str:
    return _truncate_text(text.replace("\n", " "), limit)


def _format_msg(m: RawMessage, include_date: bool) -> str:
    ts_msk = _to_msk(m.created_at)
    stamp = ts_msk.strftime("%m-%d %H:%M") if include_date else ts_msk.strftime("%H:%M")
    reactions = f" 👍×{m.reactions}" if m.reactions else ""
    return f"  {stamp} {m.author}{reactions}: {_clip(m.text)}"


def _format_authors(top_authors: list[tuple[str, int]]) -> str:
    if not top_authors:
        return "—"
    return ", ".join(f"{name} ({cnt})" for name, cnt in top_authors)


def _format_chain(chain: ReplyChain) -> list[str]:
    lines = [f"  ROOT {_to_msk(chain.root.created_at):%H:%M} {chain.root.author}: {_clip(chain.root.text)}"]
    for r in chain.replies:
        lines.append(f"    ↳ {_to_msk(r.created_at):%H:%M} {r.author}: {_clip(r.text)}")
    return lines


def _format_inner_peaks(peaks: list[tuple[datetime, datetime, int]]) -> str:
    if not peaks:
        return "—"
    parts = []
    for s, e, c in peaks:
        parts.append(f"{_to_msk(s):%H:%M}–{_to_msk(e):%H:%M} ({c} сообщ.)")
    return " · ".join(parts)


def _format_char_words(words: list[tuple[str, int, int]]) -> str:
    if not words:
        return "—"
    return ", ".join(f"{w} (в окне {bc}, в фоне {bgc})" for w, bc, bgc in words)


def _format_header(data: DigestData) -> str:
    start_msk = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end_msk = _to_msk(data.period_end).strftime("%Y-%m-%d")
    return (
        f"Период: {start_msk} — {end_msk} ({data.days} дн.), часовой пояс МСК\n"
        f"Всего сообщений: {data.total_messages} | Активных участников: {data.active_users}\n"
        f"Топ авторов: {_format_authors(data.top_authors)}"
    )


def _build_prompt(data: DigestData) -> str:
    lines: list[str] = [prompts.load("digest_task"), "", _format_header(data), ""]

    if not data.bursts:
        lines.append("Горячих окон активности не обнаружено — чат шёл ровно.")
        lines.append("")
    else:
        for i, b in enumerate(data.bursts, 1):
            start = _to_msk(b.start).strftime("%Y-%m-%d %H:%M")
            end = _to_msk(b.end).strftime("%H:%M")
            lines.append(f"=== BURST {i}: {start} — {end} МСК | {b.count} сообщ. ===")
            lines.append(f"Доминировали: {_format_authors(b.top_authors)}")
            lines.append(f"Пики плотности: {_format_inner_peaks(b.inner_peaks)}")
            lines.append(f"Характерные слова окна (TF vs фон): {_format_char_words(b.characteristic_words)}")

            if b.reply_chains:
                lines.append(f"Топ-{len(b.reply_chains)} обсуждаемых сообщения (root + ответы внутри окна):")
                for chain in b.reply_chains:
                    lines.extend(_format_chain(chain))
            else:
                lines.append("Reply-цепочек ≥2 ответов не обнаружено.")

            lines.append(f"Сэмпл сообщений окна (хронологически, {len(b.sample)} из {b.count}):")
            for m in b.sample:
                lines.append(_format_msg(m, include_date=False))
            lines.append("")

    lines.append(
        f"=== ФОН (выборка {len(data.background_sample)} из {data.background_total} сообщений вне горячих окон) ==="
    )
    if not data.background_sample:
        lines.append("  (вне горячих окон сообщений не было)")
    else:
        for m in data.background_sample:
            lines.append(_format_msg(m, include_date=True))

    text = "\n".join(lines)
    if _estimate_tokens(text) > MAX_INPUT_TOKENS:
        # отрезаем фоновые строки агрессивнее
        while lines and _estimate_tokens("\n".join(lines)) > MAX_INPUT_TOKENS:
            lines.pop(-1)
        text = "\n".join(lines)
    return text


# ---------------- public ----------------


def has_data_for_period(chat_id: int, days: int) -> bool:
    period_start = datetime.utcnow() - timedelta(days=days)
    session = SessionLocal()
    try:
        count = (
            session.query(func.count(Message.id))
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= period_start,
                Message.text.isnot(None),
                Message.text != "",
            )
            .scalar()
        )
        return (count or 0) > 0
    finally:
        session.close()


def find_active_chat_ids(window_days: int = 14) -> list[int]:
    period_start = datetime.utcnow() - timedelta(days=window_days)
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.chat_id)
            .filter(Message.created_at >= period_start)
            .distinct()
            .all()
        )
        return [r[0] for r in rows]
    finally:
        session.close()


def _format_summary_header(data: DigestData) -> str:
    start_msk = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end_msk = _to_msk(data.period_end).strftime("%Y-%m-%d")
    lines = [
        "📰 Дайджест чата",
        "",
        f"Период: {start_msk} — {end_msk} ({data.days} дн.)",
        f"Всего сообщений: {data.total_messages} | Активных участников: {data.active_users}",
        f"Топ авторов: {_format_authors(data.top_authors)}",
    ]
    if data.bursts:
        burst_summaries = []
        for i, b in enumerate(data.bursts, 1):
            s = _to_msk(b.start).strftime("%m-%d %H:%M")
            e = _to_msk(b.end).strftime("%H:%M")
            burst_summaries.append(f"B{i} {s}–{e} ({b.count})")
        lines.append(f"Горячие окна: {' · '.join(burst_summaries)}")
    return "\n".join(lines)


async def build_digest_payload(chat_id: int, days: int = DIGEST_DEFAULT_DAYS) -> tuple[str, str, DigestData | None]:
    """Возвращает (header_for_user, prompt_for_llm, data) без вызова LLM.

    Если данных нет — header содержит сообщение об этом, prompt пустой, data=None.
    """
    messages, period_start, period_end = await asyncio.to_thread(_fetch_period_messages, chat_id, days)
    if not messages:
        return f"За последние {days} дн. нет текстовых сообщений для дайджеста.", "", None

    data = await asyncio.to_thread(_build_digest_data, messages, period_start, period_end, days)
    prompt = _build_prompt(data)
    header = _format_summary_header(data)
    return header, prompt, data


async def generate_digest(chat_id: int, days: int = DIGEST_DEFAULT_DAYS) -> str:
    header, prompt, data = await build_digest_payload(chat_id, days)
    if data is None:
        return header

    digest_text = await asyncio.to_thread(
        ai_client.call_yandex,
        prompt,
        get_summary_model(),
        prompts.load("digest_system"),
    )
    return f"{header}\n\n{digest_text}"
