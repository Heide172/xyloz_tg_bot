"""tag_rentals

Revision ID: 20260515_03
Revises: 20260515_02
Create Date: 2026-05-15
"""
from alembic import op


revision = "20260515_03"
down_revision = "20260515_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tag_rentals (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            tg_user_id BIGINT NOT NULL,
            title VARCHAR(32) NOT NULL,
            price_paid INTEGER NOT NULL DEFAULT 0,
            rented_at TIMESTAMP NOT NULL DEFAULT now(),
            expires_at TIMESTAMP NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tagr_chat_status ON tag_rentals (chat_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tagr_user_status ON tag_rentals (user_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tagr_expires ON tag_rentals (status, expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tag_rentals")
