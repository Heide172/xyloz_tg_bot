"""Локальный standalone backfill эмбеддингов.

Считает эмбеддинги напрямую через sentence-transformers (без HTTP к nlp/),
автоматически использует MPS (Apple Silicon GPU) если доступен.
На M-серии Mac ускорение ~10× против CPU x86.

Зависимости (на маке):
    pip install sentence-transformers torch pgvector sqlalchemy psycopg2-binary python-dotenv

Подключение к боевой БД через SSH-туннель (в отдельном терминале):
    ssh -L 15432:localhost:5432 root@v468849 -N

Запуск:
    cd ~/projects/personal/xyloz_tg_bot
    export DATABASE_URL="postgresql://USER:PASS@localhost:15432/DBNAME"
    python scripts/embed_backfill_local.py

Опции:
    --max-batches N   ограничить число батчей (для пробного прогона)
    --batch-size N    размер батча (default 256)
    --device cpu|mps|cuda   принудительно указать устройство
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import torch
from sentence_transformers import SentenceTransformer
from sqlalchemy import func

from common.db.db import SessionLocal
from common.models.message import Message
from common.models.message_embedding import MessageEmbedding

EMBED_MODEL = os.getenv("NLP_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
MIN_TEXT_LEN = int(os.getenv("EMBED_MIN_TEXT_LEN", "10"))


def _detect_device(forced: str | None) -> str:
    if forced:
        return forced
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _count_pending() -> int:
    s = SessionLocal()
    try:
        embedded = s.query(MessageEmbedding.message_id).subquery()
        return (
            s.query(func.count(Message.id))
            .filter(
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= MIN_TEXT_LEN,
                ~Message.id.in_(embedded),
            )
            .scalar()
            or 0
        )
    finally:
        s.close()


def _fetch_pending(limit: int) -> list[tuple[int, int, str]]:
    s = SessionLocal()
    try:
        embedded = s.query(MessageEmbedding.message_id).subquery()
        rows = (
            s.query(Message.id, Message.chat_id, Message.text)
            .filter(
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= MIN_TEXT_LEN,
                ~Message.id.in_(embedded),
            )
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        return [(r[0], r[1], (r[2] or "").strip()) for r in rows if r[2] and r[2].strip()]
    finally:
        s.close()


def _save(rows: list[tuple[int, int, str]], vectors) -> int:
    if not rows:
        return 0
    now = datetime.utcnow()
    s = SessionLocal()
    try:
        for (msg_id, chat_id, _text), vec in zip(rows, vectors):
            s.merge(MessageEmbedding(
                message_id=msg_id,
                chat_id=chat_id,
                embedding=vec.tolist(),
                created_at=now,
            ))
        s.commit()
        return len(rows)
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--encode-batch-size", type=int, default=64)
    parser.add_argument("--device", default=None, choices=["cpu", "mps", "cuda"])
    args = parser.parse_args()

    pending = _count_pending()
    print(f"pending messages to embed: {pending}")
    if pending == 0:
        return

    device = _detect_device(args.device)
    print(f"loading {EMBED_MODEL} on device={device}")
    model = SentenceTransformer(EMBED_MODEL, device=device)
    print("model ready")

    batch_no = 0
    total = 0
    started = time.time()
    while True:
        batch_no += 1
        if args.max_batches and batch_no > args.max_batches:
            print(f"stop: max-batches={args.max_batches}")
            break
        rows = _fetch_pending(args.batch_size)
        if not rows:
            remaining = _count_pending()
            if remaining == 0:
                print("done: nothing left")
                break
            print(f"batch returned 0 but {remaining} still pending; abort")
            break
        texts = [t for _, _, t in rows]
        with torch.no_grad():
            vectors = model.encode(
                texts,
                batch_size=args.encode_batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        saved = _save(rows, vectors)
        total += saved
        elapsed = time.time() - started
        rate = total / elapsed if elapsed else 0
        eta_sec = (pending - total) / rate if rate else 0
        print(f"batch {batch_no}: +{saved} (total {total}/{pending}, {rate:.1f}/s, ETA ~{int(eta_sec)}s)")


if __name__ == "__main__":
    main()
