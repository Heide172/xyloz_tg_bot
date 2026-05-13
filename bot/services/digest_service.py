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
BURST_MAX_WIDTH_HOURS = 2
INNER_PEAK_SLOT_MIN = 10
INNER_PEAK_TOP_K = 2
INNER_PEAK_CONTEXT_MIN = 3

# Reply chains
REPLY_CHAIN_TOP = 4
REPLY_CHAIN_MAX_REPLIES = 6
REPLY_CHAIN_MIN_REPLIES = 2

# Characteristic n-grams
CHARACTERISTIC_UNIGRAMS_TOP = 6
CHARACTERISTIC_BIGRAMS_TOP = 6
UNIGRAM_MIN_COUNT = 4
BIGRAM_MIN_COUNT = 2

# Quote candidates
QUOTE_CANDIDATES_TOP = 8
QUOTE_MIN_WORDS = 5
QUOTE_MIN_CHARS = 30

# Sampling
SAMPLE_MIN_WORDS = 5
SAMPLE_MIN_CHARS = 25
BURST_SAMPLE_PER_WINDOW = 15
BACKGROUND_SAMPLE_LIMIT = 25
TOP_AUTHOR_LIMIT = 5

MSK = ZoneInfo("Europe/Moscow")

# Слово: первая буква, потом ещё 4+ буквенно-дефисных символа (итого 5+ символов).
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{4,}")

RU_STOP = {
    "этот", "этого", "этому", "этом", "этим", "эта", "эту", "этой", "эти", "этих",
    "того", "тому", "тех", "той", "там", "тут", "туда", "сюда",
    "вообще", "просто", "значит", "конечно", "наверное", "максимум",
    "всегда", "никогда", "иногда", "часто", "редко", "сейчас", "сегодня", "вчера", "завтра",
    "если", "когда", "потом", "после", "перед", "пока", "тоже", "также", "ещё", "уже",
    "очень", "сильно", "слабо", "немного", "много", "мало", "несколько",
    "можно", "нельзя", "нужно", "надо", "должен", "должна", "должны",
    "буду", "будем", "будешь", "будет", "будут", "была", "было", "были", "быть",
    "меня", "тебя", "нас", "вас", "них", "ему", "ней", "ним", "ими", "мне", "тебе", "нам", "вам", "им",
    "себе", "себя", "своим", "своей", "свою", "своё", "своих",
    "моей", "моим", "моих", "твоей", "твоим", "твоих", "нашей", "нашим", "наших", "вашей", "вашим", "ваших",
    "который", "которая", "которые", "которое", "которых", "которому", "которой", "которым",
    "другой", "другая", "другое", "другие", "другому", "другую", "другим",
    "такой", "такая", "такое", "такие", "такому", "такую", "таким",
    "сказал", "сказала", "сказали", "говорит", "говорил", "говорила",
    "хочу", "хочет", "хотел", "хотела", "хотим", "хотят", "хочется", "хотелось",
    "делаю", "делает", "делал", "делала", "делают", "делаем",
    "знаю", "знает", "знал", "знала", "знаешь", "знают", "знаем",
    "думаю", "думает", "думал", "думала", "думаешь", "думают", "думаем",
    "смотри", "смотрит", "смотрел", "смотрела", "смотрите", "смотрят",
    "блин", "ладно", "кстати", "короче", "типа", "ну-ну",
    "from", "with", "this", "that", "what", "they", "them", "were", "have", "been", "will",
    "just", "like", "yeah", "okay", "really", "would", "could", "should",
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
    inner_peaks: list[tuple[datetime, datetime, int]]
    char_unigrams: list[tuple[str, int, int]]  # (word, in_burst, in_bg)
    char_bigrams: list[tuple[str, int, int]]   # (phrase, in_burst, in_bg)
    reply_chains: list[ReplyChain]
    quote_candidates: list[RawMessage] = field(default_factory=list)
    sample: list[RawMessage] = field(default_factory=list)
    short_messages_omitted: int = 0


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


def _word_count(text: str) -> int:
    return len(text.split())


def _is_substantive(text: str) -> bool:
    return _word_count(text) >= SAMPLE_MIN_WORDS or len(text) >= SAMPLE_MIN_CHARS


# ---------------- data fetching ----------------


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


SPLIT_PEAK_GAP_MIN = 60   # если пики разнесены больше — дробим окно
SPLIT_PEAK_CONTEXT_MIN = 15  # контекст вокруг каждого пика при дроблении


def _split_or_narrow_burst(
    burst: tuple[datetime, datetime],
    in_window: list[RawMessage],
) -> list[tuple[datetime, datetime]]:
    """Возвращает список под-окон.

    - Если окно <= BURST_MAX_WIDTH_HOURS — оставляем как есть.
    - Если есть 2+ пика и они разнесены >= SPLIT_PEAK_GAP_MIN — **дробим** на отдельные под-окна.
    - Если пики близко — сужаем до объединения пиков ± контекст.
    - Если пиков нет — оставляем как есть.
    """
    start, end = burst
    if end - start <= timedelta(hours=BURST_MAX_WIDTH_HOURS):
        return [burst]

    peaks = _find_inner_peaks(in_window)
    if not peaks:
        return [burst]

    if len(peaks) >= 2:
        first_end = peaks[0][1]
        second_start = peaks[1][0]
        gap = second_start - first_end
        if gap >= timedelta(minutes=SPLIT_PEAK_GAP_MIN):
            ctx = timedelta(minutes=SPLIT_PEAK_CONTEXT_MIN)
            sub_windows = []
            for p_start, p_end, _ in peaks:
                sub_start = max(p_start - ctx, start)
                sub_end = min(p_end + ctx, end)
                if sub_end - sub_start >= timedelta(minutes=INNER_PEAK_SLOT_MIN):
                    sub_windows.append((sub_start, sub_end))
            if sub_windows:
                return sub_windows

    # Пики близко друг к другу — сужаем до их объединения.
    ctx = timedelta(minutes=INNER_PEAK_CONTEXT_MIN)
    new_start = max(min(p[0] for p in peaks) - ctx, start)
    new_end = min(max(p[1] for p in peaks) + ctx, end)
    if new_end - new_start < timedelta(minutes=INNER_PEAK_SLOT_MIN):
        return [burst]
    return [(new_start, new_end)]


# ---------------- reply chains ----------------


def _build_reply_chains(in_window: list[RawMessage]) -> list[ReplyChain]:
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


# ---------------- characteristic words / bigrams ----------------


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text) if w.lower() not in RU_STOP]


def _unigram_counts(messages: list[RawMessage]) -> Counter[str]:
    c: Counter[str] = Counter()
    for m in messages:
        for w in _tokens(m.text):
            c[w] += 1
    return c


def _bigram_counts(messages: list[RawMessage]) -> Counter[tuple[str, str]]:
    c: Counter[tuple[str, str]] = Counter()
    for m in messages:
        toks = _tokens(m.text)
        for a, b in zip(toks, toks[1:]):
            c[(a, b)] += 1
    return c


def _score_characteristic(
    burst_counts: Counter,
    bg_counts: Counter,
    min_count: int,
    top_n: int,
) -> list[tuple, ...]:
    burst_total = max(1, sum(burst_counts.values()))
    bg_total = max(1, sum(bg_counts.values()))
    alpha = 1.0 / (burst_total + bg_total)

    scored: list[tuple] = []
    for key, cnt in burst_counts.items():
        if cnt < min_count:
            continue
        bf = cnt / burst_total
        gf = bg_counts.get(key, 0) / bg_total
        ratio = (bf + alpha) / (gf + alpha)
        scored.append((key, ratio, cnt, bg_counts.get(key, 0)))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


def _characteristic_words_and_bigrams(
    burst_msgs: list[RawMessage],
    background_msgs: list[RawMessage],
) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    if not burst_msgs:
        return [], []

    bu = _unigram_counts(burst_msgs)
    bgu = _unigram_counts(background_msgs)
    unigram_top = _score_characteristic(bu, bgu, UNIGRAM_MIN_COUNT, CHARACTERISTIC_UNIGRAMS_TOP)
    unigrams = [(w, c, bgc) for w, _r, c, bgc in unigram_top]

    bb = _bigram_counts(burst_msgs)
    bgb = _bigram_counts(background_msgs)
    bigram_top = _score_characteristic(bb, bgb, BIGRAM_MIN_COUNT, CHARACTERISTIC_BIGRAMS_TOP)
    bigrams = [(" ".join(bg), c, bgc) for bg, _r, c, bgc in bigram_top]
    return unigrams, bigrams


# ---------------- quote candidates ----------------


def _pick_quote_candidates(messages: list[RawMessage]) -> list[RawMessage]:
    eligible = [
        m for m in messages
        if _word_count(m.text) >= QUOTE_MIN_WORDS and len(m.text) >= QUOTE_MIN_CHARS
    ]
    # сортируем: сначала с реакциями, потом длина (как proxy для содержания)
    eligible.sort(key=lambda m: (-m.reactions, -len(m.text)))
    return eligible[:QUOTE_CANDIDATES_TOP]


# ---------------- sample assembly ----------------


def _build_burst_sample(
    in_window: list[RawMessage],
    chain_msg_ids: set[int],
) -> tuple[list[RawMessage], int]:
    """Сэмпл из non-chain сообщений, отфильтрованных по длине; сортированный по реакциям."""
    candidates = [m for m in in_window if m.db_id not in chain_msg_ids]
    substantive = [m for m in candidates if _is_substantive(m.text)]
    short_count = len(candidates) - len(substantive)

    substantive.sort(key=lambda m: (-m.reactions, m.created_at))
    sample = substantive[:BURST_SAMPLE_PER_WINDOW]
    sample.sort(key=lambda m: m.created_at)
    return sample, short_count


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
            char_unigrams=[], char_bigrams=[], reply_chains=[],
        )

    author_counts = Counter(m.author for m in in_window)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)
    inner_peaks = _find_inner_peaks(in_window)
    unigrams, bigrams = _characteristic_words_and_bigrams(in_window, background_msgs)
    chains = _build_reply_chains(in_window)

    chain_msg_ids: set[int] = set()
    for c in chains:
        chain_msg_ids.add(c.root.db_id)
        chain_msg_ids.update(r.db_id for r in c.replies)

    sample, short_omitted = _build_burst_sample(in_window, chain_msg_ids)
    quote_candidates = _pick_quote_candidates(in_window)

    return BurstContext(
        start=start,
        end=end,
        count=len(in_window),
        top_authors=top_authors,
        inner_peaks=inner_peaks,
        char_unigrams=unigrams,
        char_bigrams=bigrams,
        reply_chains=chains,
        quote_candidates=quote_candidates,
        sample=sample,
        short_messages_omitted=short_omitted,
    )


def _build_background_sample(
    messages: list[RawMessage],
    burst_windows: list[tuple[datetime, datetime]],
) -> tuple[list[RawMessage], int]:
    def in_any_burst(m: RawMessage) -> bool:
        for s, e in burst_windows:
            if s <= m.created_at < e:
                return True
        return False

    background_all = [m for m in messages if not in_any_burst(m)]
    background = [m for m in background_all if _is_substantive(m.text)]
    total = len(background_all)
    if len(background) <= BACKGROUND_SAMPLE_LIMIT:
        return sorted(background, key=lambda m: m.created_at), total

    step = len(background) / BACKGROUND_SAMPLE_LIMIT
    sampled = [background[min(int(i * step), len(background) - 1)] for i in range(BACKGROUND_SAMPLE_LIMIT)]
    sampled.sort(key=lambda m: m.created_at)
    return sampled, total


def _build_digest_data(messages: list[RawMessage], period_start: datetime, period_end: datetime, days: int) -> DigestData:
    author_counts = Counter(m.author for m in messages)
    top_authors = author_counts.most_common(TOP_AUTHOR_LIMIT)
    active_users = len(author_counts)

    initial_windows = _find_hour_bursts(messages)

    # Дробим / сужаем каждое исходное окно до его реальных пиков.
    refined_windows: list[tuple[datetime, datetime]] = []
    for w in initial_windows:
        in_w = [m for m in messages if w[0] <= m.created_at < w[1]]
        refined_windows.extend(_split_or_narrow_burst(w, in_w))
    refined_windows.sort(key=lambda x: x[0])

    bg_msgs_initial = [
        m for m in messages
        if not any(s <= m.created_at < e for s, e in refined_windows)
    ]

    bursts: list[BurstContext] = []
    for w in refined_windows:
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


# ---------------- prompt formatting ----------------


def _clip(text: str, limit: int = MAX_CHARS_PER_MESSAGE) -> str:
    return _truncate_text(text.replace("\n", " "), limit)


def _format_msg(m: RawMessage, include_date: bool) -> str:
    ts = _to_msk(m.created_at)
    stamp = ts.strftime("%m-%d %H:%M") if include_date else ts.strftime("%H:%M")
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
    return " · ".join(
        f"{_to_msk(s):%H:%M}–{_to_msk(e):%H:%M} ({c} сообщ.)" for s, e, c in peaks
    )


def _format_ngrams(items: list[tuple[str, int, int]]) -> str:
    if not items:
        return "—"
    return ", ".join(f"«{w}» (в окне {bc}, в фоне {bgc})" for w, bc, bgc in items)


def _format_header(data: DigestData) -> str:
    start = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end = _to_msk(data.period_end).strftime("%Y-%m-%d")
    return (
        f"Период: {start} — {end} ({data.days} дн.), часовой пояс МСК\n"
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
            lines.append(f"Характерные слова (TF vs фон): {_format_ngrams(b.char_unigrams)}")
            lines.append(f"Характерные пары слов (TF vs фон): {_format_ngrams(b.char_bigrams)}")

            if b.reply_chains:
                lines.append(f"Топ-{len(b.reply_chains)} обсуждаемых сообщения (root + ответы):")
                for chain in b.reply_chains:
                    lines.extend(_format_chain(chain))
            else:
                lines.append("Reply-цепочек ≥2 ответов не обнаружено.")

            if b.quote_candidates:
                lines.append(f"КАНДИДАТЫ В ЦИТАТЫ (только из них или ничего):")
                for idx, q in enumerate(b.quote_candidates, 1):
                    ts = _to_msk(q.created_at).strftime("%H:%M")
                    reactions = f" 👍×{q.reactions}" if q.reactions else ""
                    lines.append(f"  [Q{i}.{idx}] {ts} {q.author}{reactions}: {_clip(q.text)}")
            else:
                lines.append("КАНДИДАТЫ В ЦИТАТЫ: пусто (длинных сообщений нет — цитат не делай).")

            short_note = (
                f" (кроме {b.short_messages_omitted} коротких реплик-междометий)"
                if b.short_messages_omitted
                else ""
            )
            lines.append(
                f"Сэмпл сообщений окна (хронологически, отфильтрованы короткие, {len(b.sample)} из {b.count}{short_note}):"
            )
            for m in b.sample:
                lines.append(_format_msg(m, include_date=False))
            lines.append("")

    lines.append(
        f"=== ФОН (выборка {len(data.background_sample)} из {data.background_total} сообщений вне горячих окон, короткие отброшены) ==="
    )
    if not data.background_sample:
        lines.append("  (вне горячих окон содержательных сообщений не было)")
    else:
        for m in data.background_sample:
            lines.append(_format_msg(m, include_date=True))

    text = "\n".join(lines)
    if _estimate_tokens(text) > MAX_INPUT_TOKENS:
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
    start = _to_msk(data.period_start).strftime("%Y-%m-%d")
    end = _to_msk(data.period_end).strftime("%Y-%m-%d")
    lines = [
        "📰 Дайджест чата",
        "",
        f"Период: {start} — {end} ({data.days} дн.)",
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
        ai_client.call,
        prompt,
        get_summary_model(),
        prompts.load("digest_system"),
    )
    return f"{header}\n\n{digest_text}"
