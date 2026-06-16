"""gacha visual rework: daily bonus + affection (приласкать)

Revision ID: 20260616_01
Revises: 20260603_01
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260616_01"
down_revision = "20260603_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clicker_farms",
        sa.Column("last_daily_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "gacha_collection",
        sa.Column("affection", sa.Integer(), nullable=False, server_default="0"),
    )
    # server_default нужен только для backfill существующих строк; снимаем,
    # дальше значение задаёт ORM-дефолт.
    op.alter_column("gacha_collection", "affection", server_default=None)


def downgrade() -> None:
    op.drop_column("gacha_collection", "affection")
    op.drop_column("clicker_farms", "last_daily_at")
