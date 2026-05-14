"""clicker_farms

Revision ID: 20260514_05
Revises: 20260514_04
Create Date: 2026-05-14
"""
from alembic import op


revision = "20260514_05"
down_revision = "20260514_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS clicker_farms (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            cp_balance BIGINT NOT NULL DEFAULT 0,
            tap_level INTEGER NOT NULL DEFAULT 1,
            auto_level INTEGER NOT NULL DEFAULT 0,
            lifetime_cp BIGINT NOT NULL DEFAULT 0,
            last_seen_at TIMESTAMP NOT NULL DEFAULT now(),
            daily_converted INTEGER NOT NULL DEFAULT 0,
            daily_window_start TIMESTAMP NOT NULL DEFAULT now(),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_clicker_farms_user_chat UNIQUE (user_id, chat_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_clicker_farms_chat ON clicker_farms (chat_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS clicker_farms")
