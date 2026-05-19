from datetime import datetime

from sqlalchemy import BIGINT, Column, DateTime, Float, Index

from common.db.base import Base


class ClickerMarketPool(Base):
    """AMM-пул фермы пер-чат (constant-product).

    Курс cp/гривна = r_cp / r_h. Конвертация cp→гривна двигает цену вниз,
    обратная покупка — вверх. Резервы — float (восстановление = экспонента
    к якорю, не должно копить целочисленный дрейф).
    """
    __tablename__ = "clicker_market_pool"

    chat_id = Column(BIGINT, primary_key=True)
    r_cp = Column(Float, nullable=False)
    r_h = Column(Float, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ClickerMarketPrice(Base):
    """Снапшот курса на тике восстановления — для графика «живого рынка»."""
    __tablename__ = "clicker_market_price"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    chat_id = Column(BIGINT, nullable=False)
    ts = Column(DateTime, nullable=False, default=datetime.utcnow)
    rate = Column(Float, nullable=False)  # cp за 1 гривну (r_cp / r_h)

    __table_args__ = (
        Index("idx_clicker_market_price_chat_ts", "chat_id", "ts"),
    )
