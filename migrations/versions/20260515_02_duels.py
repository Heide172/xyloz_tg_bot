"""duels

Revision ID: 20260515_02
Revises: 20260515_01
Create Date: 2026-05-15
"""
from alembic import op


revision = "20260515_02"
down_revision = "20260515_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS duels (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            challenger_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            opponent_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            stake INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            winner_id BIGINT,
            commission INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            resolved_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_duels_chat_status ON duels (chat_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_duels_opponent ON duels (opponent_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_duels_challenger ON duels (challenger_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS duels")
