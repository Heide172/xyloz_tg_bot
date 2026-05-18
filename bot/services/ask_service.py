"""RAG-сервис: гибридный (вектор + лексика) поиск в истории чата +
LLM-ответ с цитатами."""
import asyncio
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import func

from common import prompts
from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.message import Message
from common.models.message_embedding import MessageEmbedding
from common.models.user import User
from services import ai_client
from services.summary_service import get_summary_model

logger = get_logger(__name__)

NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp:8000").rstrip("/")
EMBED_TIMEOUT_SEC = float(os.getenv("NLP_EMBED_TIMEOUT_SEC", "60"))

ASK_TOP_K = int(os.getenv("ASK_TOP_K", "25"))
ASK_NEIGHBORS_EACH_SIDE = int(os.getenv("ASK_NEIGHBORS_EACH_SIDE", "2"))
ASK_REWRITE_VARIANTS = int(os.getenv("ASK_REWRITE_VARIANTS", "3"))
ASK_PER_QUERY_K = int(os.getenv("ASK_PER_QUERY_K", "15"))
ASK_MIN_QUERY_LEN = 3
MSK = ZoneInfo("Europe/Moscow")

# Стоп-слова: вопросительные/служебные, не несут темы поиска.
_STOP = {
    "как", "много", "сколько", "раз", "про", "что", "чем", "чём", "кто",
    "где", "когда", "почему", "зачем", "была", "были", "было", "был",
    "это", "эта", "этот", "тот", "там", "тут", "она", "они", "оно",
    "его", "ему", "нам", "вам", "või", "или", "ещё", "уже", "вообще",
    "говорил", "говорила", "говорили", "писал", "писала", "обсуждал",
    "обсуждали", "тему", "теме", "часто", "редко",
    "пользователь", "пользователя", "юзер", "юзера", "человек", "чел",
}


def _extract_author(query: str) -> str | None:
    m = re.search(r"@([A-Za-z0-9_]{3,32})", query)
    return m.group(1) if m else None


def _keyword_terms(query: str) -> list[str]:
    """Значимые слова темы: длина ≥4, не стоп-слова, без @mention."""
    q = re.sub(r"@[A-Za-z0-9_]{3,32}", " ", query.lower())
    words = re.findall(r"[\wёа-я]{4,}", q, flags=re.UNICODE)
    terms = []
    for w in words:
        if w in _STOP or w.isdigit():
            continue
        terms.append(w)
    return terms[:6]


def _term_root(term: str) -> str:
    """Грубый стемминг: отрезаем рус. окончание (≤2 буквы), мин длина 4.
    'дроны'→'дрон' → ILIKE '%дрон%' ловит дрон/дроны/дронов/дроне."""
    if len(term) > 5:
        return term[:-2]
    if len(term) > 4:
        return term[:-1]
    return term


def parse_ask_query(text: str | None) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Использование: /ask <вопрос>")
    q = parts[1].strip()
    if len(q) < ASK_MIN_QUERY_LEN:
        raise ValueError("Вопрос слишком короткий.")
    return q


async def _embed_queries(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    url = f"{NLP_SERVICE_URL}/embed/batch"
    timeout = aiohttp.ClientTimeout(total=EMBED_TIMEOUT_SEC)
    async with aiohttp.ClientSession() as http:
        async with http.post(url, json={"texts": texts}, timeout=timeout) as resp:
            resp.raise_for_status()
            body = await resp.json()
    return body.get("embeddings") or []


async def _embed_query(text: str) -> list[float] | None:
    embeds = await _embed_queries([text])
    return embeds[0] if embeds else None


async def _rewrite_query(query: str) -> list[str]:
    """Возвращает список формулировок: [original, variant1, variant2, ...]."""
    task = prompts.load("ask_query_rewrite_task").format(query=query)
    try:
        raw = await asyncio.to_thread(
            ai_client.call,
            task,
            get_summary_model(),
            prompts.load("ask_query_rewrite_system"),
        )
    except Exception:
        logger.exception("query rewrite failed, using only original")
        return [query]

    variants = [query]
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # на всякий случай чистим нумерацию/маркеры
        import re
        m = re.match(r"^[\d\-\*•.)\s]+(.+)$", line)
        if m:
            line = m.group(1).strip()
        line = line.strip('"\'«»`')
        if line and line.lower() != query.lower() and line not in variants:
            variants.append(line)
        if len(variants) >= 1 + ASK_REWRITE_VARIANTS:
            break
    return variants


def _to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def _author_label(username: str | None, fullname: str | None) -> str:
    if username:
        return f"@{username}"
    if fullname:
        return fullname
    return "Unknown"


def _search_similar(chat_id: int, query_vec: list[float], k: int) -> list[dict]:
    session = SessionLocal()
    try:
        distance = MessageEmbedding.embedding.cosine_distance(query_vec)
        rows = (
            session.query(Message, User, distance.label("dist"))
            .join(MessageEmbedding, MessageEmbedding.message_id == Message.id)
            .outerjoin(User, Message.user_id == User.id)
            .filter(MessageEmbedding.chat_id == chat_id)
            .order_by(distance)
            .limit(k)
            .all()
        )
        results = []
        for msg, user, dist in rows:
            results.append({
                "id": msg.id,
                "text": (msg.text or "").strip(),
                "created_at": msg.created_at,
                "author": _author_label(user.username if user else None, user.fullname if user else None),
                "similarity": float(1.0 - dist),
                "is_hit": True,
            })
        return results
    finally:
        session.close()


def _search_lexical(
    chat_id: int, terms: list[str], author: str | None, k: int
) -> list[dict]:
    """Точный лексический поиск по словам темы (ILIKE по корню),
    опционально только сообщения @author. Закрывает пробел чистого
    вектора для конкретных слов ('дроны') и count-вопросов про юзера."""
    if not terms:
        return []
    session = SessionLocal()
    try:
        roots = [_term_root(t) for t in terms]
        q = (
            session.query(Message, User)
            .outerjoin(User, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.text.isnot(None),
                Message.text != "",
            )
        )
        # OR по корням термов
        cond = None
        for r in roots:
            c = Message.text.ilike(f"%{r}%")
            cond = c if cond is None else (cond | c)
        q = q.filter(cond)
        if author:
            q = q.filter(func.lower(User.username) == author.lower())
        rows = (
            q.order_by(Message.created_at.desc()).limit(k).all()
        )
        results = []
        for msg, user in rows:
            txt = (msg.text or "").strip()
            low = txt.lower()
            matched = sum(1 for r in roots if r in low)
            results.append({
                "id": msg.id,
                "text": txt,
                "created_at": msg.created_at,
                "author": _author_label(
                    user.username if user else None,
                    user.fullname if user else None,
                ),
                # автор-скоуп — прямой ответ на вопрос про юзера, ставим
                # высокий приоритет, чтобы merge не срезал
                "similarity": (0.97 if author else 0.80) + 0.01 * matched,
                "is_hit": True,
            })
        return results
    finally:
        session.close()


def _expand_with_neighbors(chat_id: int, hits: list[dict], each_side: int) -> list[dict]:
    """Для каждого hit'а добавляем по N соседних сообщений с каждой стороны (по позиции в чате)."""
    if not hits or each_side <= 0:
        return hits

    session = SessionLocal()
    try:
        all_results: dict[int, dict] = {h["id"]: h for h in hits}
        for hit in hits:
            # До: предыдущие N сообщений по created_at
            before = (
                session.query(Message, User)
                .outerjoin(User, Message.user_id == User.id)
                .filter(
                    Message.chat_id == chat_id,
                    Message.created_at < hit["created_at"],
                    Message.text.isnot(None),
                    Message.text != "",
                )
                .order_by(Message.created_at.desc())
                .limit(each_side)
                .all()
            )
            # После: следующие N сообщений
            after = (
                session.query(Message, User)
                .outerjoin(User, Message.user_id == User.id)
                .filter(
                    Message.chat_id == chat_id,
                    Message.created_at > hit["created_at"],
                    Message.text.isnot(None),
                    Message.text != "",
                )
                .order_by(Message.created_at.asc())
                .limit(each_side)
                .all()
            )
            for msg, user in list(before) + list(after):
                if msg.id in all_results:
                    continue
                all_results[msg.id] = {
                    "id": msg.id,
                    "text": (msg.text or "").strip(),
                    "created_at": msg.created_at,
                    "author": _author_label(
                        user.username if user else None,
                        user.fullname if user else None,
                    ),
                    "similarity": 0.0,
                    "is_hit": False,
                }
        merged = sorted(all_results.values(), key=lambda r: r["created_at"])
        return merged
    finally:
        session.close()


def _format_context_for_llm(query: str, results: list[dict]) -> str:
    hits_count = sum(1 for r in results if r.get("is_hit"))
    lines = [
        prompts.load("ask_task"),
        "",
        f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {query}",
        "",
        f"НАЙДЕННЫЕ СООБЩЕНИЯ (★ релевантных: {hits_count}, плюс по ±{ASK_NEIGHBORS_EACH_SIDE} соседних сообщения вокруг каждого ★ для контекста; всего: {len(results)}; отсортированы хронологически):",
    ]
    for r in results:
        ts = _to_msk(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        text = r["text"].replace("\n", " ")
        if len(text) > 300:
            text = text[:300] + "…"
        if r.get("is_hit"):
            marker = f"★[sim={r['similarity']:.2f}]"
        else:
            marker = "·"
        lines.append(f"{marker} {ts} МСК {r['author']}: {text}")
    lines.append("")
    lines.append("★ — найдено по поиску; · — соседнее сообщение (контекст вокруг хита).")
    return "\n".join(lines)


def _merge_hits(per_query_hits: list[list[dict]]) -> list[dict]:
    """Объединяем хиты из всех variant-поисков; для одного message_id берём max similarity."""
    merged: dict[int, dict] = {}
    for hits in per_query_hits:
        for h in hits:
            existing = merged.get(h["id"])
            if existing is None or h["similarity"] > existing["similarity"]:
                merged[h["id"]] = h
    return sorted(merged.values(), key=lambda x: -x["similarity"])[:ASK_TOP_K]


async def stream_ask(
    chat_id: int,
    query: str,
    on_delta=None,
    on_reasoning=None,
) -> tuple[str, str, list[dict]]:
    """Возвращает (header, llm_answer, results).

    Pipeline:
      1) LLM переписывает вопрос в 3 перефразировки (recall buff)
      2) Embed всех вариантов батчем
      3) Search каждым → объединяем по max similarity → top-K
      4) Соседи ±2 для контекста
      5) LLM-ответ с цитатами
    """
    variants = await _rewrite_query(query)
    embeds = await _embed_queries(variants)
    if not embeds:
        return "Не удалось получить эмбеддинг вопроса.", "", []

    per_query_hits: list[list[dict]] = []
    for vec in embeds:
        hits = await asyncio.to_thread(_search_similar, chat_id, vec, ASK_PER_QUERY_K)
        per_query_hits.append(hits)

    # Гибрид: лексический поиск по словам темы. Если в вопросе есть
    # @username — тянем сообщения именно этого автора (точный ответ на
    # «как много X говорил про Y», count-вопросы).
    author = _extract_author(query)
    terms = _keyword_terms(query)
    if terms:
        lex_k = ASK_PER_QUERY_K * 3 if author else ASK_PER_QUERY_K
        lex = await asyncio.to_thread(
            _search_lexical, chat_id, terms, author, lex_k
        )
        if lex:
            per_query_hits.append(lex)

    hits = _merge_hits(per_query_hits)
    if not hits:
        return (
            "По этому чату нет проэмбедженных сообщений (ещё идёт backfill?).",
            "",
            [],
        )

    results = await asyncio.to_thread(_expand_with_neighbors, chat_id, hits, ASK_NEIGHBORS_EACH_SIDE)
    prompt = _format_context_for_llm(query, results)
    answer = await asyncio.to_thread(
        ai_client.stream,
        prompt,
        get_summary_model(),
        on_delta or (lambda _d: None),
        prompts.load("ask_system"),
        on_reasoning,
    )

    variants_note = ""
    if len(variants) > 1:
        variants_note = f"\nПерефразировок: {len(variants)} (orig + {len(variants)-1})"
    header = (
        f"Вопрос: {query}{variants_note}\n"
        f"Найдено релевантных: {len(hits)} (+{len(results) - len(hits)} соседей)"
    )
    return header, answer, results
