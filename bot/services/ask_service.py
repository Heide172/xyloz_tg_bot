"""RAG-сервис: семантический поиск в истории чата + LLM-ответ с цитатами."""
import asyncio
import os
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

ASK_TOP_K = int(os.getenv("ASK_TOP_K", "20"))
ASK_MIN_QUERY_LEN = 3
MSK = ZoneInfo("Europe/Moscow")


def parse_ask_query(text: str | None) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Использование: /ask <вопрос>")
    q = parts[1].strip()
    if len(q) < ASK_MIN_QUERY_LEN:
        raise ValueError("Вопрос слишком короткий.")
    return q


async def _embed_query(text: str) -> list[float] | None:
    url = f"{NLP_SERVICE_URL}/embed/batch"
    timeout = aiohttp.ClientTimeout(total=EMBED_TIMEOUT_SEC)
    async with aiohttp.ClientSession() as http:
        async with http.post(url, json={"texts": [text]}, timeout=timeout) as resp:
            resp.raise_for_status()
            body = await resp.json()
    embeds = body.get("embeddings") or []
    return embeds[0] if embeds else None


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
            })
        return results
    finally:
        session.close()


def _format_context_for_llm(query: str, results: list[dict]) -> str:
    lines = [
        prompts.load("ask_task"),
        "",
        f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {query}",
        "",
        f"НАЙДЕННЫЕ СООБЩЕНИЯ (отсортированы по релевантности, всего {len(results)}):",
    ]
    for r in results:
        ts = _to_msk(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        sim = r["similarity"]
        text = r["text"].replace("\n", " ")
        if len(text) > 300:
            text = text[:300] + "…"
        lines.append(f"[sim={sim:.2f}] {ts} МСК {r['author']}: {text}")
    return "\n".join(lines)


async def stream_ask(
    chat_id: int,
    query: str,
    on_delta=None,
    on_reasoning=None,
) -> tuple[str, str, list[dict]]:
    """Возвращает (header, llm_answer, results).

    Если эмбеддингов не найдено — header содержит ошибку, остальное пустое.
    """
    vec = await _embed_query(query)
    if vec is None:
        return "Не удалось получить эмбеддинг вопроса.", "", []

    results = await asyncio.to_thread(_search_similar, chat_id, vec, ASK_TOP_K)
    if not results:
        return (
            "🔎 По этому чату нет проэмбедженных сообщений (ещё идёт backfill?).",
            "",
            [],
        )

    prompt = _format_context_for_llm(query, results)
    answer = await asyncio.to_thread(
        ai_client.stream,
        prompt,
        get_summary_model(),
        on_delta or (lambda _d: None),
        prompts.load("ask_system"),
        on_reasoning,
    )

    header = f"🔎 Вопрос: {query}\n📚 Найдено релевантных: {len(results)}"
    return header, answer, results
