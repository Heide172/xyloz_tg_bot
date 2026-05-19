"""casino_games idempotency key

Revision ID: 20260519_05
Revises: 20260519_04
Create Date: 2026-05-19
"""
from alembic import op


revision = "20260519_05"
down_revision = "20260519_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE casino_games ADD COLUMN IF NOT EXISTS idem_key VARCHAR(40)"
    )
    # Один и тот же ключ от юзера = одна игра (защита от двойного списания
    # при ретрае после потери ответа во время редеплоя).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_casino_games_user_idem "
        "ON casino_games (user_id, idem_key) WHERE idem_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_casino_games_user_idem")
    op.execute("ALTER TABLE casino_games DROP COLUMN IF EXISTS idem_key")
