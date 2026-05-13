"""Идемпотентная миграция: добавляет NLP-поля в messages.

Запуск:
    docker compose exec bot python scripts/apply_nlp_migration.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from common.db.db import engine

STATEMENTS = [
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS sentiment_score FLOAT",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS sentiment_label VARCHAR(20)",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS toxicity_score FLOAT",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS topic_id INTEGER",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS nlp_processed_at TIMESTAMP",
    "CREATE INDEX IF NOT EXISTS idx_nlp_unprocessed ON messages (nlp_processed_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sentiment ON messages (chat_id, sentiment_label)",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in STATEMENTS:
            print(f"-> {sql}")
            conn.exec_driver_sql(sql)
    print("schema updated")


if __name__ == "__main__":
    main()
