"""Идемпотентная миграция pgvector. Создаёт extension и таблицу message_embeddings.

Требует superuser-привилегий для CREATE EXTENSION (если pgvector ещё не установлен в БД).
"""
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

from common.db.db import engine

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS message_embeddings (
        message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        chat_id BIGINT NOT NULL,
        embedding vector(384) NOT NULL,
        created_at TIMESTAMP DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_message_embeddings_chat ON message_embeddings (chat_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_embeddings_vec ON message_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in STATEMENTS:
            print(f"-> {sql.split(chr(10))[0][:80]}")
            conn.exec_driver_sql(sql)
    print("pgvector migration applied")


if __name__ == "__main__":
    main()
