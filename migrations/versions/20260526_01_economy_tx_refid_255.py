"""economy_tx.ref_id varchar(80) → varchar(255)

Telegram Stars telegram_payment_charge_id ~144 символа — не помещался,
из-за чего падал INSERT для kind='stars_topup'.

Revision ID: 20260526_01
Revises: 20260519_05
Create Date: 2026-05-26
"""
from alembic import op


revision = "20260526_01"
down_revision = "20260519_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE economy_tx ALTER COLUMN ref_id TYPE varchar(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE economy_tx ALTER COLUMN ref_id TYPE varchar(80)"
    )
