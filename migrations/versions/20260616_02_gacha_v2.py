"""gacha v2: gems, level/exp, PvP rating + telemetry tables

Revision ID: 20260616_02
Revises: 20260616_01
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260616_02"
down_revision = "20260616_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # clicker_farms: валюта gems, pity-флаг, PvP-рейтинг
    op.add_column("clicker_farms", sa.Column("gems", sa.BIGINT(), nullable=False, server_default="0"))
    op.add_column("clicker_farms", sa.Column("rate_up_lost", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("clicker_farms", sa.Column("pvp_elo", sa.Integer(), nullable=False, server_default="1000"))
    op.add_column("clicker_farms", sa.Column("pvp_wins", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("clicker_farms", sa.Column("pvp_losses", sa.Integer(), nullable=False, server_default="0"))
    for col in ("gems", "rate_up_lost", "pvp_elo", "pvp_wins", "pvp_losses"):
        op.alter_column("clicker_farms", col, server_default=None)

    # gacha_collection: уровень/опыт карты
    op.add_column("gacha_collection", sa.Column("level", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("gacha_collection", sa.Column("exp", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("gacha_collection", "level", server_default=None)
    op.alter_column("gacha_collection", "exp", server_default=None)

    # телеметрия боёв
    op.create_table(
        "pvp_battles",
        sa.Column("id", sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BIGINT(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="matchmake"),
        sa.Column("a_user_id", sa.BIGINT(), nullable=True),
        sa.Column("b_user_id", sa.BIGINT(), nullable=True),
        sa.Column("winner", sa.String(4), nullable=False),
        sa.Column("winner_user_id", sa.BIGINT(), nullable=True),
        sa.Column("rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stake", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("team_a", JSONB(), nullable=False, server_default="[]"),
        sa.Column("team_b", JSONB(), nullable=False, server_default="[]"),
        sa.Column("log", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_pvp_battles_chat_created", "pvp_battles", ["chat_id", "created_at"])
    op.create_index("idx_pvp_battles_a", "pvp_battles", ["a_user_id"])

    # телеметрия круток
    op.create_table(
        "gacha_roll_log",
        sa.Column("id", sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("chat_id", sa.BIGINT(), nullable=False),
        sa.Column("char_id", sa.String(40), nullable=False),
        sa.Column("rarity", sa.String(8), nullable=False),
        sa.Column("pity_ssr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pity_ur", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("soft_pity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hard_pity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rate_up_win", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_x10", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gem_cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_gacha_roll_log_chat_created", "gacha_roll_log", ["chat_id", "created_at"])
    op.create_index("idx_gacha_roll_log_char", "gacha_roll_log", ["char_id"])


def downgrade() -> None:
    op.drop_table("gacha_roll_log")
    op.drop_table("pvp_battles")
    op.drop_column("gacha_collection", "exp")
    op.drop_column("gacha_collection", "level")
    for col in ("pvp_losses", "pvp_wins", "pvp_elo", "rate_up_lost", "gems"):
        op.drop_column("clicker_farms", col)
