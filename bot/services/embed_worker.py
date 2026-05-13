import asyncio
import os
from datetime import datetime

import aiohttp
from sqlalchemy import exists, func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.message import Message
from common.models.message_embedding import MessageEmbedding

logger = get_logger(__name__)

NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp:8000").rstrip("/")
EMBED_WORKER_BATCH = int(os.getenv("EMBED_WORKER_BATCH", "100"))
EMBED_HTTP_TIMEOUT_SEC = float(os.getenv("NLP_EMBED_TIMEOUT_SEC", "120"))
EMBED_MIN_TEXT_LEN = int(os.getenv("EMBED_MIN_TEXT_LEN", "10"))


def _fetch_pending_batch(limit: int) -> list[tuple[int, int, str]]:
    """Возвращает [(message_id, chat_id, text)]."""
    session = SessionLocal()
    try:
        embedded = session.query(MessageEmbedding.message_id).subquery()
        rows = (
            session.query(Message.id, Message.chat_id, Message.text)
            .filter(
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= EMBED_MIN_TEXT_LEN,
                ~Message.id.in_(embedded),
            )
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        return [(r[0], r[1], (r[2] or "").strip()) for r in rows if r[2] and r[2].strip()]
    finally:
        session.close()


async def _embed_via_nlp(session: aiohttp.ClientSession, texts: list[str]) -> list[list[float]]:
    timeout = aiohttp.ClientTimeout(total=EMBED_HTTP_TIMEOUT_SEC)
    url = f"{NLP_SERVICE_URL}/embed/batch"
    async with session.post(url, json={"texts": texts}, timeout=timeout) as resp:
        resp.raise_for_status()
        body = await resp.json()
    return body.get("embeddings") or []


def _save_embeddings(rows: list[tuple[int, int, str]], embeddings: list[list[float]]) -> int:
    if len(embeddings) != len(rows):
        logger.warning("embed: results length %d != batch %d, truncating", len(embeddings), len(rows))
    n = min(len(rows), len(embeddings))
    if n == 0:
        return 0
    now = datetime.utcnow()
    session = SessionLocal()
    try:
        for (msg_id, chat_id, _text), vec in zip(rows[:n], embeddings[:n]):
            session.merge(MessageEmbedding(
                message_id=msg_id,
                chat_id=chat_id,
                embedding=vec,
                created_at=now,
            ))
        session.commit()
        return n
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def embed_pending_once() -> int:
    rows = await asyncio.to_thread(_fetch_pending_batch, EMBED_WORKER_BATCH)
    if not rows:
        return 0
    texts = [t for _, _, t in rows]
    async with aiohttp.ClientSession() as http:
        try:
            embeddings = await _embed_via_nlp(http, texts)
        except Exception:
            logger.exception("embed: nlp request failed (batch=%d)", len(texts))
            return 0
    saved = await asyncio.to_thread(_save_embeddings, rows, embeddings)
    logger.info("embed: saved %d embeddings", saved)
    return saved
