"""vpn-digest: monitored chats, messages, digests

Revision ID: 20260603_01
Revises: 20260527_01
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "20260603_01"
down_revision = "20260527_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn_monitored_chats",
        sa.Column("id", sa.BIGINT(), primary_key=True),
        sa.Column("title", sa.String(255)),
        sa.Column("username", sa.String(255)),
        sa.Column("is_forum", sa.Boolean(), default=False),
        sa.Column("enabled", sa.Boolean(), default=True),
        sa.Column("added_at", sa.DateTime()),
    )

    op.create_table(
        "vpn_messages",
        sa.Column("id", sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BIGINT(), nullable=False),
        sa.Column("telegram_message_id", sa.BIGINT(), nullable=False),
        sa.Column("user_id", sa.BIGINT()),
        sa.Column("username", sa.String(255)),
        sa.Column("text", sa.Text()),
        sa.Column("reply_to", sa.BIGINT()),
        sa.Column("topic_id", sa.BIGINT()),
        sa.Column("topic_title", sa.String(255)),
        sa.Column("is_forwarded", sa.Boolean(), default=False),
        sa.Column("has_media", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("edited_at", sa.DateTime()),
    )
    op.create_index("uq_vpn_chat_tg_message", "vpn_messages", ["chat_id", "telegram_message_id"], unique=True)
    op.create_index("idx_vpn_chat_created", "vpn_messages", ["chat_id", "created_at"])
    op.create_index("idx_vpn_chat_topic_created", "vpn_messages", ["chat_id", "topic_id", "created_at"])

    op.create_table(
        "vpn_digests",
        sa.Column("id", sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("chat_id", sa.BIGINT()),
        sa.Column("content", sa.Text()),
        sa.Column("model", sa.String(100)),
        sa.Column("messages_count", sa.Integer(), default=0),
        sa.Column("delivered", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("idx_vpn_digest_period_end", "vpn_digests", ["period_end"])


def downgrade() -> None:
    op.drop_table("vpn_digests")
    op.drop_table("vpn_messages")
    op.drop_table("vpn_monitored_chats")
