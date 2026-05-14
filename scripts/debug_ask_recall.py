"""Sanity-check: ищем сообщение с известным текстом, смотрим эмбеддинг и его место в поиске."""
import sys
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

from common.db.db import engine, SessionLocal
from common.models.message import Message
from common.models.message_embedding import MessageEmbedding


SEARCH_TEXT = "трактор"
QUERY = "кто рассказывал историю про трактор в болоте"


def find_messages_with(needle: str, limit: int = 5):
    s = SessionLocal()
    try:
        rows = (
            s.query(Message.id, Message.chat_id, Message.text, Message.created_at)
            .filter(Message.text.ilike(f"%{needle}%"))
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        return rows
    finally:
        s.close()


def check_embedding_exists(msg_id: int) -> bool:
    s = SessionLocal()
    try:
        return s.query(MessageEmbedding.message_id).filter(MessageEmbedding.message_id == msg_id).first() is not None
    finally:
        s.close()


def search_topk(chat_id: int, query_vec, k: int = 30, probes: int | None = None):
    s = SessionLocal()
    try:
        if probes is not None:
            s.execute(MessageEmbedding.__table__.select().limit(0))  # ensure connection
            s.connection().exec_driver_sql(f"SET ivfflat.probes = {probes}")
        distance = MessageEmbedding.embedding.cosine_distance(query_vec)
        rows = (
            s.query(Message.id, Message.text, distance.label("d"))
            .join(MessageEmbedding, MessageEmbedding.message_id == Message.id)
            .filter(MessageEmbedding.chat_id == chat_id)
            .order_by(distance)
            .limit(k)
            .all()
        )
        return rows
    finally:
        s.close()


def main():
    print(f"Ищем сообщения с подстрокой «{SEARCH_TEXT}»...")
    candidates = find_messages_with(SEARCH_TEXT, limit=10)
    if not candidates:
        print("ничего не найдено по полному совпадению")
        return

    print(f"Найдено {len(candidates)} сообщений (топ 10):")
    for r in candidates:
        emb_exists = check_embedding_exists(r.id)
        text = r.text[:120].replace("\n", " ")
        emb_mark = "✓emb" if emb_exists else "✗NO_EMB"
        print(f"  msg_id={r.id} chat={r.chat_id} [{emb_mark}] {r.created_at:%Y-%m-%d %H:%M}: {text}")

    target = candidates[0]
    print(f"\nИспользуем как target: msg_id={target.id}, chat={target.chat_id}")

    print(f"\nЭмбеддим query: «{QUERY}»")
    model = SentenceTransformer(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        device="mps" if torch.backends.mps.is_available() else "cpu",
    )
    with torch.no_grad():
        qvec = model.encode([QUERY], normalize_embeddings=True)[0].tolist()

    for probes in (1, 10, 50, 100):
        print(f"\n-- probes={probes} --")
        rows = search_topk(target.chat_id, qvec, k=50, probes=probes)
        target_rank = None
        for rank, (mid, _t, d) in enumerate(rows, 1):
            if mid == target.id:
                target_rank = rank
                break
        if target_rank:
            print(f"target message rank: {target_rank}/50 (cosine_distance={float(rows[target_rank-1].d):.4f})")
        else:
            print("target message NOT in top-50")
        print("top 5 results:")
        for mid, t, d in rows[:5]:
            t_clip = t[:90].replace("\n", " ")
            print(f"  rank: dist={float(d):.4f} msg_id={mid}: {t_clip}")


if __name__ == "__main__":
    main()
