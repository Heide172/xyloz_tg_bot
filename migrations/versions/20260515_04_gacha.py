"""gacha_collection + clicker_farms gacha columns

Revision ID: 20260515_04
Revises: 20260515_03
Create Date: 2026-05-15
"""
from alembic import op


revision = "20260515_04"
down_revision = "20260515_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS gacha_collection (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            char_id VARCHAR(40) NOT NULL,
            stars INTEGER NOT NULL DEFAULT 1,
            copies INTEGER NOT NULL DEFAULT 1,
            obtained_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_gacha_user_chat_char UNIQUE (user_id, chat_id, char_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_gacha_user_chat ON gacha_collection (user_id, chat_id)")
    for col, ddl in [
        ("pity_ssr", "INTEGER NOT NULL DEFAULT 0"),
        ("pity_ur", "INTEGER NOT NULL DEFAULT 0"),
        ("gacha_rolls", "INTEGER NOT NULL DEFAULT 0"),
        ("active_heroine", "VARCHAR(40)"),
        ("gacha_migrated", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        op.execute(
            f"ALTER TABLE clicker_farms ADD COLUMN IF NOT EXISTS {col} {ddl}"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gacha_collection")
    for col in ["pity_ssr", "pity_ur", "gacha_rolls", "active_heroine", "gacha_migrated"]:
        op.execute(f"ALTER TABLE clicker_farms DROP COLUMN IF EXISTS {col}")
