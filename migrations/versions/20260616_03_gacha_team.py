"""gacha v2: сохранённый боевой состав (расстановка)

Revision ID: 20260616_03
Revises: 20260616_02
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260616_03"
down_revision = "20260616_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clicker_farms", sa.Column("team", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("clicker_farms", "team")
