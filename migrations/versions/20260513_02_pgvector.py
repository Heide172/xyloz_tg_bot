"""add pgvector extension and message_embeddings table

Revision ID: 20260513_02
Revises: 20260513_01
Create Date: 2026-05-13
"""
from alembic import op


revision = "20260513_02"
down_revision = "20260513_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS message_embeddings (
            message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            embedding vector(384) NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_message_embeddings_chat ON message_embeddings (chat_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_embeddings_vec "
        "ON message_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_vec")
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_chat")
    op.execute("DROP TABLE IF EXISTS message_embeddings")
