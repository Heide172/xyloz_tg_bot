"""Идемпотентно создаёт таблицы экономики (user_balance, economy_tx, chat_bank)."""
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
    """CREATE TABLE IF NOT EXISTS user_balance (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        chat_id BIGINT NOT NULL,
        balance INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, chat_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_user_balance_chat ON user_balance (chat_id)",
    """CREATE TABLE IF NOT EXISTS economy_tx (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        chat_id BIGINT NOT NULL,
        amount INTEGER NOT NULL,
        kind VARCHAR(40) NOT NULL,
        ref_id VARCHAR(80),
        note TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_economy_tx_user_chat ON economy_tx (user_id, chat_id)",
    "CREATE INDEX IF NOT EXISTS idx_economy_tx_chat_kind ON economy_tx (chat_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_economy_tx_created_at ON economy_tx (created_at)",
    """CREATE TABLE IF NOT EXISTS chat_bank (
        chat_id BIGINT PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "INSERT INTO alembic_version (version_num) VALUES ('20260514_02') ON CONFLICT (version_num) DO NOTHING",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in STATEMENTS:
            print(f"-> {sql.split(chr(10))[0][:80]}")
            conn.exec_driver_sql(sql)
    print("economy tables ready")


if __name__ == "__main__":
    main()
