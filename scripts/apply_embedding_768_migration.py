"""Идемпотентная миграция таблицы message_embeddings под 768-dim (mpnet).

ВНИМАНИЕ: удаляет все существующие эмбеддинги. После этого нужен backfill.

Запуск:
    python scripts/apply_embedding_768_migration.py
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


def main() -> None:
    with engine.begin() as c:
        before = c.exec_driver_sql("SELECT count(*) FROM message_embeddings").scalar() or 0
        print(f"existing rows in message_embeddings: {before}")
        print("dropping table and indexes...")
        c.exec_driver_sql("DROP INDEX IF EXISTS idx_message_embeddings_vec")
        c.exec_driver_sql("DROP INDEX IF EXISTS idx_message_embeddings_chat")
        c.exec_driver_sql("DROP TABLE IF EXISTS message_embeddings")
        print("creating table with vector(768)...")
        c.exec_driver_sql("""
            CREATE TABLE message_embeddings (
                message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                embedding vector(768) NOT NULL,
                created_at TIMESTAMP DEFAULT now()
            )
        """)
        c.exec_driver_sql("CREATE INDEX idx_message_embeddings_chat ON message_embeddings (chat_id)")
        c.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('20260514_01') ON CONFLICT (version_num) DO NOTHING"
        )
    print("done — table recreated with vector(768). Now run backfill.")


if __name__ == "__main__":
    main()
