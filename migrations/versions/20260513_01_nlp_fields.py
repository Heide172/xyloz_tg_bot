"""add nlp fields to messages

Revision ID: 20260513_01
Revises:
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = "20260513_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sentiment_score", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("sentiment_label", sa.String(length=20), nullable=True))
    op.add_column("messages", sa.Column("toxicity_score", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("topic_id", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("nlp_processed_at", sa.DateTime(), nullable=True))

    op.create_index("idx_nlp_unprocessed", "messages", ["nlp_processed_at"])
    op.create_index("idx_chat_sentiment", "messages", ["chat_id", "sentiment_label"])


def downgrade() -> None:
    op.drop_index("idx_chat_sentiment", table_name="messages")
    op.drop_index("idx_nlp_unprocessed", table_name="messages")
    op.drop_column("messages", "nlp_processed_at")
    op.drop_column("messages", "topic_id")
    op.drop_column("messages", "toxicity_score")
    op.drop_column("messages", "sentiment_label")
    op.drop_column("messages", "sentiment_score")
