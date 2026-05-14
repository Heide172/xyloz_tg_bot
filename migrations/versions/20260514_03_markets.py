"""markets/market_options/bets

Revision ID: 20260514_03
Revises: 20260514_02
Create Date: 2026-05-14
"""
from alembic import op


revision = "20260514_03"
down_revision = "20260514_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS markets (
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
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_markets_chat_status ON markets (chat_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_markets_closes_at ON markets (closes_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS market_options (
            id BIGSERIAL PRIMARY KEY,
            market_id BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
            label VARCHAR(200) NOT NULL,
            pool INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_market_options_market ON market_options (market_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id BIGSERIAL PRIMARY KEY,
            market_id BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
            option_id BIGINT NOT NULL REFERENCES market_options(id) ON DELETE CASCADE,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            amount INTEGER NOT NULL,
            payout INTEGER,
            refunded INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bets_market_option ON bets (market_id, option_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bets")
    op.execute("DROP TABLE IF EXISTS market_options")
    op.execute("DROP TABLE IF EXISTS markets")
