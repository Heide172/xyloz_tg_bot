"""feedback reward bookkeeping

Revision ID: 20260519_02
Revises: 20260519_01
Create Date: 2026-05-19
"""
from alembic import op


revision = "20260519_02"
down_revision = "20260519_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS reward INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS rewarded_at TIMESTAMP"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE feedback DROP COLUMN IF EXISTS rewarded_at")
    op.execute("ALTER TABLE feedback DROP COLUMN IF EXISTS reward")
