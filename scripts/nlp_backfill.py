"""Backfill NLP-полей для исторических сообщений.

Запуск из контейнера bot:
    docker compose exec bot python scripts/nlp_backfill.py

Опционально указать максимальное число батчей:
    docker compose exec bot python scripts/nlp_backfill.py --max-batches 200
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
from services.nlp_classifier import classify_pending_once  # noqa: E402


def _count_pending() -> int:
    session = SessionLocal()
    try:
        return (
            session.query(func.count(Message.id))
            .filter(
                Message.nlp_processed_at.is_(None),
                Message.text.isnot(None),
                Message.text != "",
            )
            .scalar()
            or 0
        )
    finally:
        session.close()


async def run(max_batches: int | None) -> None:
    pending = _count_pending()
    print(f"pending messages: {pending}")
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

        updated = await classify_pending_once()
        if updated == 0:
            remaining = _count_pending()
            if remaining == 0:
                print("done: nothing left to process")
                break
            print(f"batch returned 0 but {remaining} still pending — pausing 5s")
            await asyncio.sleep(5)
            continue

        processed_total += updated
        elapsed = time.time() - started
        rate = processed_total / elapsed if elapsed > 0 else 0
        print(f"batch {batch_no}: +{updated} (total {processed_total}, {rate:.1f}/s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.max_batches))


if __name__ == "__main__":
    main()
