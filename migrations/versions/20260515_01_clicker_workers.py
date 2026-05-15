"""clicker_farms.workers

Revision ID: 20260515_01
Revises: 20260514_05
Create Date: 2026-05-15
"""
from alembic import op


revision = "20260515_01"
down_revision = "20260514_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clicker_farms "
        "ADD COLUMN IF NOT EXISTS workers JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE clicker_farms DROP COLUMN IF EXISTS workers")
