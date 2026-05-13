"""Backfill эмбеддингов через nlp/ сервис (запуск на сервере).

Для локального быстрого прогона на маке с MPS см. embed_backfill_local.py.

Запуск из контейнера bot:
    docker compose exec bot python scripts/embed_backfill.py
    docker compose exec bot python scripts/embed_backfill.py --max-batches 100
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from sqlalchemy import func  # noqa: E402

from common.db.db import SessionLocal  # noqa: E402
from common.models.message import Message  # noqa: E402
from common.models.message_embedding import MessageEmbedding  # noqa: E402
from services.embed_worker import EMBED_MIN_TEXT_LEN, embed_pending_once  # noqa: E402


def _count_pending() -> int:
    session = SessionLocal()
    try:
        embedded = session.query(MessageEmbedding.message_id).subquery()
        return (
            session.query(func.count(Message.id))
            .filter(
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= EMBED_MIN_TEXT_LEN,
                ~Message.id.in_(embedded),
            )
            .scalar()
            or 0
        )
    finally:
        session.close()


async def run(max_batches: int | None) -> None:
    pending = _count_pending()
    print(f"pending messages to embed: {pending}")
    if pending == 0:
        return

    processed_total = 0
    started = time.time()
    batch_no = 0
    while True:
        batch_no += 1
        if max_batches and batch_no > max_batches:
            print(f"stop: max_batches={max_batches} reached")
            break
        saved = await embed_pending_once()
        if saved == 0:
            remaining = _count_pending()
            if remaining == 0:
                print("done: nothing left to embed")
                break
            print(f"batch returned 0 but {remaining} still pending — pausing 5s")
            await asyncio.sleep(5)
            continue
        processed_total += saved
        elapsed = time.time() - started
        rate = processed_total / elapsed if elapsed > 0 else 0
        print(f"batch {batch_no}: +{saved} (total {processed_total}, {rate:.1f}/s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.max_batches))


if __name__ == "__main__":
    main()
