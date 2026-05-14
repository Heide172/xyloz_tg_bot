"""casino_games

Revision ID: 20260514_04
Revises: 20260514_03
Create Date: 2026-05-14
"""
from alembic import op


revision = "20260514_04"
down_revision = "20260514_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS casino_games (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            game VARCHAR(20) NOT NULL,
            bet INTEGER NOT NULL,
            payout INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'finished',
            outcome VARCHAR(20),
            state JSONB,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            finished_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_casino_games_user_chat ON casino_games (user_id, chat_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_casino_games_status ON casino_games (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_casino_games_game ON casino_games (game)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS casino_games")
