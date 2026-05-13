import asyncio
import os
from datetime import datetime
from typing import Iterable

import aiohttp
from sqlalchemy import update

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.message import Message

logger = get_logger(__name__)

NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp:8000").rstrip("/")
NLP_BATCH_SIZE = int(os.getenv("NLP_WORKER_BATCH", "200"))
NLP_TIMEOUT_SEC = float(os.getenv("NLP_HTTP_TIMEOUT_SEC", "60"))


def _fetch_pending_batch(limit: int) -> list[tuple[int, str]]:
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.id, Message.text)
            .filter(
                Message.nlp_processed_at.is_(None),
                Message.text.isnot(None),
                Message.text != "",
            )
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        return [(r[0], r[1].strip()) for r in rows if r[1] and r[1].strip()]
    finally:
        session.close()


async def _classify_via_nlp(session: aiohttp.ClientSession, texts: list[str]) -> list[dict]:
    url = f"{NLP_SERVICE_URL}/classify/batch"
    timeout = aiohttp.ClientTimeout(total=NLP_TIMEOUT_SEC)
    async with session.post(url, json={"texts": texts}, timeout=timeout) as resp:
        resp.raise_for_status()
        body = await resp.json()
    return body.get("results", [])


def _apply_results(rows: list[tuple[int, str]], results: list[dict]) -> int:
    if len(results) != len(rows):
        logger.warning("nlp results length %d != batch %d, aligning by min", len(results), len(rows))
    now = datetime.utcnow()
    updated = 0
    session = SessionLocal()
    try:
        for (msg_id, _text), res in zip(rows, results):
            session.execute(
                update(Message)
                .where(Message.id == msg_id)
                .values(
                    sentiment_label=res.get("sentiment_label"),
                    sentiment_score=res.get("sentiment_score"),
                    toxicity_score=res.get("toxicity_score"),
                    nlp_processed_at=now,
                )
            )
            updated += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return updated


async def classify_pending_once() -> int:
    rows = await asyncio.to_thread(_fetch_pending_batch, NLP_BATCH_SIZE)
    if not rows:
        return 0

    texts = [t for _, t in rows]
    async with aiohttp.ClientSession() as http:
        try:
            results = await _classify_via_nlp(http, texts)
        except Exception:
            logger.exception("nlp classify request failed (batch=%d)", len(texts))
            return 0

    updated = await asyncio.to_thread(_apply_results, rows, results)
    logger.info("nlp: classified %d messages", updated)
    return updated
