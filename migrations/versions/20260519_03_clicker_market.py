"""clicker AMM market pool + price log; drop daily-cap cols

Revision ID: 20260519_03
Revises: 20260519_02
Create Date: 2026-05-19
"""
from alembic import op


revision = "20260519_03"
down_revision = "20260519_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS clicker_market_pool (
            chat_id BIGINT PRIMARY KEY,
            r_cp DOUBLE PRECISION NOT NULL,
            r_h DOUBLE PRECISION NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS clicker_market_price (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            ts TIMESTAMP NOT NULL DEFAULT now(),
            rate DOUBLE PRECISION NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_clicker_market_price_chat_ts "
        "ON clicker_market_price (chat_id, ts)"
    )
    # Старый daily-cap больше не нужен (заменён AMM).
    op.execute("ALTER TABLE clicker_farms DROP COLUMN IF EXISTS daily_converted")
    op.execute("ALTER TABLE clicker_farms DROP COLUMN IF EXISTS daily_window_start")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE clicker_farms ADD COLUMN IF NOT EXISTS "
        "daily_converted INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE clicker_farms ADD COLUMN IF NOT EXISTS "
        "daily_window_start TIMESTAMP NOT NULL DEFAULT now()"
    )
    op.execute("DROP TABLE IF EXISTS clicker_market_price")
    op.execute("DROP TABLE IF EXISTS clicker_market_pool")
