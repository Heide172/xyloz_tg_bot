"""feedback

Revision ID: 20260519_01
Revises: 20260515_04
Create Date: 2026-05-19
"""
from alembic import op


revision = "20260519_01"
down_revision = "20260515_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            chat_id BIGINT,
            kind VARCHAR(16) NOT NULL,
            text TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'new',
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_feedback_kind_status ON feedback (kind, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback")
