"""AMM-рынок фермы (constant-product) пер-чат.

cp — товар, гривна — деньги. Курс cp/гривна = r_cp / r_h.
- sell_cp: ферма продаёт cp → давит цену вниз (slippage).
- buy_cp:  гривна → cp (обратный поток, под будущую гачу/ККИ) → цену вверх.
Восстановление: тик тянет резервы экспонентой к якорю (mean-reversion).

Заменяет старый монотонный курс (CP_PER_HRYVNIA + minted//scale) и
дневной кэп. Никакого подушевого лимита — рынок сам себе тормоз.
"""
import math
import os
from datetime import datetime, timedelta

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.clicker_market import ClickerMarketPool, ClickerMarketPrice
from services.markets_service import InvalidArgument

logger = get_logger(__name__)

# Якорь курса: сколько cp за 1 гривну в равновесии.
ANCHOR_RATE = float(os.getenv("MARKET_ANCHOR_RATE", "100"))
# Глубина пула в гривнах (R_h0). R_cp0 = R_h0 * ANCHOR_RATE.
R_H0 = float(os.getenv("MARKET_R_H0", "200000"))
# Восстановление к якорю: τ (мин) и шаг тика (мин).
TAU_MIN = float(os.getenv("MARKET_TAU_MIN", "240"))
TICK_MIN = float(os.getenv("MARKET_TICK_MIN", "10"))
# Сколько суток держим снапшоты цены.
PRICE_RETAIN_DAYS = int(os.getenv("MARKET_PRICE_RETAIN_DAYS", "7"))


def _anchor() -> tuple[float, float]:
    """(R_cp0, R_h0)."""
    return R_H0 * ANCHOR_RATE, R_H0


def get_or_create_pool(session, chat_id: int) -> ClickerMarketPool:
    row = (
        session.query(ClickerMarketPool)
        .filter(ClickerMarketPool.chat_id == chat_id)
        .with_for_update()
        .first()
    )
    if row:
        return row
    r_cp0, r_h0 = _anchor()
    row = ClickerMarketPool(
        chat_id=chat_id, r_cp=r_cp0, r_h=r_h0, updated_at=datetime.utcnow()
    )
    session.add(row)
    session.flush()
    return row


def spot_rate(pool: ClickerMarketPool) -> float:
    """Текущий курс: cp за 1 гривну."""
    return pool.r_cp / pool.r_h if pool.r_h > 0 else float("inf")


def sell_cp(session, chat_id: int, cp: int) -> int:
    """Продать cp в пул → гривны (constant-product, со slippage).
    Мутирует пул. Возвращает гривны (int, floor). Не коммитит."""
    if cp <= 0:
        raise InvalidArgument("cp должно быть > 0")
    pool = get_or_create_pool(session, chat_id)
    k = pool.r_cp * pool.r_h
    out = pool.r_h - k / (pool.r_cp + cp)
    out_i = int(math.floor(max(0.0, out)))
    if out_i < 1:
        raise InvalidArgument(
            "Рынок обвален (цена cp ≈ 0) — подожди восстановления"
        )
    pool.r_cp += cp
    pool.r_h -= out_i
    pool.updated_at = datetime.utcnow()
    return out_i


def buy_cp(session, chat_id: int, hryvnia: int) -> int:
    """Купить cp за гривны (обратный поток) → давит курс вверх.
    Мутирует пул. Возвращает cp (int, floor). Не коммитит."""
    if hryvnia <= 0:
        raise InvalidArgument("Сумма должна быть > 0")
    pool = get_or_create_pool(session, chat_id)
    k = pool.r_cp * pool.r_h
    cp_out = pool.r_cp - k / (pool.r_h + hryvnia)
    cp_i = int(math.floor(max(0.0, cp_out)))
    if cp_i < 1:
        raise InvalidArgument("Слишком мелкая сумма для текущего курса")
    pool.r_h += hryvnia
    pool.r_cp -= cp_i
    pool.updated_at = datetime.utcnow()
    return cp_i


def quote(session, chat_id: int) -> dict:
    pool = get_or_create_pool(session, chat_id)
    return {
        "rate": round(spot_rate(pool), 2),       # cp за гривну
        "r_cp": round(pool.r_cp, 2),
        "r_h": round(pool.r_h, 2),
        "anchor_rate": ANCHOR_RATE,
    }


def quote_sync(chat_id: int) -> dict:
    """Котировка с собственной сессией (для API/бота)."""
    session = SessionLocal()
    try:
        q = quote(session, chat_id)
        session.commit()
        return q
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_pool(session, chat_id: int) -> None:
    """Сброс пула к якорю (используется ручным вайпом)."""
    pool = get_or_create_pool(session, chat_id)
    r_cp0, r_h0 = _anchor()
    pool.r_cp = r_cp0
    pool.r_h = r_h0
    pool.updated_at = datetime.utcnow()


def price_history(chat_id: int, limit: int = 200) -> list[dict]:
    session = SessionLocal()
    try:
        rows = (
            session.query(ClickerMarketPrice)
            .filter(ClickerMarketPrice.chat_id == chat_id)
            .order_by(ClickerMarketPrice.ts.desc())
            .limit(limit)
            .all()
        )
        return [
            {"ts": r.ts.isoformat(), "rate": round(r.rate, 2)}
            for r in reversed(rows)
        ]
    finally:
        session.close()


def recover_and_snapshot_all() -> int:
    """Тик планировщика: тянем все пулы к якорю и пишем снапшот цены.
    Возвращает число обработанных пулов."""
    factor = math.exp(-TICK_MIN / TAU_MIN)
    r_cp0, r_h0 = _anchor()
    session = SessionLocal()
    n = 0
    try:
        now = datetime.utcnow()
        pools = session.query(ClickerMarketPool).all()
        for p in pools:
            p.r_cp = r_cp0 + (p.r_cp - r_cp0) * factor
            p.r_h = r_h0 + (p.r_h - r_h0) * factor
            p.updated_at = now
            session.add(ClickerMarketPrice(
                chat_id=p.chat_id, ts=now,
                rate=(p.r_cp / p.r_h if p.r_h > 0 else 0.0),
            ))
            n += 1
        cutoff = now - timedelta(days=PRICE_RETAIN_DAYS)
        session.query(ClickerMarketPrice).filter(
            ClickerMarketPrice.ts < cutoff
        ).delete(synchronize_session=False)
        session.commit()
        return n
    except Exception:
        session.rollback()
        logger.exception("market recover tick failed")
        return 0
    finally:
        session.close()
