"""resize message_embeddings to vector(768) for mpnet-base-v2

Revision ID: 20260514_01
Revises: 20260513_02
Create Date: 2026-05-14

ВНИМАНИЕ: миграция уничтожает существующие эмбеддинги (384-dim).
После этой миграции нужен полный backfill.
"""
from alembic import op


revision = "20260514_01"
down_revision = "20260513_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_vec")
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_chat")
    op.execute("DROP TABLE IF EXISTS message_embeddings")
    op.execute("""
        CREATE TABLE message_embeddings (
            message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            embedding vector(768) NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_message_embeddings_chat ON message_embeddings (chat_id)")
    # ivfflat-индекс создаём после backfill (через manage_pgvector_index.py create)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_vec")
    op.execute("DROP INDEX IF EXISTS idx_message_embeddings_chat")
    op.execute("DROP TABLE IF EXISTS message_embeddings")
    op.execute("""
        CREATE TABLE message_embeddings (
            message_id BIGINT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            embedding vector(384) NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_message_embeddings_chat ON message_embeddings (chat_id)")
