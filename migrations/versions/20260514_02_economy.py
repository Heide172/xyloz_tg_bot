"""economy: user_balance, economy_tx, chat_bank

Revision ID: 20260514_02
Revises: 20260514_01
Create Date: 2026-05-14
"""
from alembic import op


revision = "20260514_02"
down_revision = "20260514_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_balance (
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_balance_chat ON user_balance (chat_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS economy_tx (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            chat_id BIGINT NOT NULL,
            amount INTEGER NOT NULL,
            kind VARCHAR(40) NOT NULL,
            ref_id VARCHAR(80),
            note TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_economy_tx_user_chat ON economy_tx (user_id, chat_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_economy_tx_chat_kind ON economy_tx (chat_id, kind)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_economy_tx_created_at ON economy_tx (created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_bank (
            chat_id BIGINT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_bank")
    op.execute("DROP TABLE IF EXISTS economy_tx")
    op.execute("DROP TABLE IF EXISTS user_balance")
