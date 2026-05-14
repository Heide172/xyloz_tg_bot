"""Идемпотентно создаёт таблицы markets/market_options/bets."""
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
    """CREATE TABLE IF NOT EXISTS markets (
        id BIGSERIAL PRIMARY KEY,
        chat_id BIGINT NOT NULL,
        type VARCHAR(20) NOT NULL DEFAULT 'internal',
        question TEXT NOT NULL,
        creator_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        closes_at TIMESTAMP NOT NULL,
        resolved_at TIMESTAMP,
        winning_option_id BIGINT,
        external_url TEXT,
        external_id VARCHAR(120),
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_markets_chat_status ON markets (chat_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_markets_closes_at ON markets (closes_at)",
    """CREATE TABLE IF NOT EXISTS market_options (
        id BIGSERIAL PRIMARY KEY,
        market_id BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
        label VARCHAR(200) NOT NULL,
        pool INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_market_options_market ON market_options (market_id)",
    """CREATE TABLE IF NOT EXISTS bets (
        id BIGSERIAL PRIMARY KEY,
        market_id BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
        option_id BIGINT NOT NULL REFERENCES market_options(id) ON DELETE CASCADE,
        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        amount INTEGER NOT NULL,
        payout INTEGER,
        refunded INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_bets_market_option ON bets (market_id, option_id)",
    "CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id)",
    "INSERT INTO alembic_version (version_num) VALUES ('20260514_03') ON CONFLICT (version_num) DO NOTHING",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in STATEMENTS:
            print(f"-> {sql.split(chr(10))[0][:80]}")
            conn.exec_driver_sql(sql)
    print("markets tables ready")


if __name__ == "__main__":
    main()
