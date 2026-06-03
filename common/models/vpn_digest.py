from datetime import datetime

from sqlalchemy import Column, BIGINT, Integer, String, Text, DateTime, Boolean, Index

from common.db.base import Base


class VpnDigest(Base):
    """История сгенерированных дайджестов по VPN-чатам."""

    __tablename__ = "vpn_digests"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    period_start = Column(DateTime, nullable=False)  # UTC
    period_end = Column(DateTime, nullable=False)  # UTC
    chat_id = Column(BIGINT)  # NULL = общий дайджест по всем чатам

    content = Column(Text)  # markdown
    model = Column(String(100))
    messages_count = Column(Integer, default=0)

    delivered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_vpn_digest_period_end", "period_end"),
    )
