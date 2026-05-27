"""twin state, consent, log

Revision ID: 20260527_01
Revises: 20260526_01
Create Date: 2026-05-27
"""
from alembic import op


revision = "20260527_01"
down_revision = "20260526_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_twin_state (
            chat_id BIGINT PRIMARY KEY,
            target_user_id BIGINT,
            target_tg_id BIGINT,
            target_name VARCHAR(128),
            day_msk DATE,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            paused_until TIMESTAMP,
            replies_today INTEGER NOT NULL DEFAULT 0,
            last_reply_at TIMESTAMP,
            persona_stats JSONB,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS twin_consent (
            user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS twin_log (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            target_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            trigger_message_id BIGINT,
            response_text TEXT NOT NULL,
            cost INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'sent',
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_twinlog_chat_created "
        "ON twin_log (chat_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS twin_log")
    op.execute("DROP TABLE IF EXISTS twin_consent")
    op.execute("DROP TABLE IF EXISTS chat_twin_state")
