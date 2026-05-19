"""app_events usage analytics

Revision ID: 20260519_04
Revises: 20260519_03
Create Date: 2026-05-19
"""
from alembic import op


revision = "20260519_04"
down_revision = "20260519_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_events (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            chat_id BIGINT,
            event VARCHAR(48) NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            ts TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_app_events_ts ON app_events (ts)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_events_event_ts "
        "ON app_events (event, ts)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_events")
