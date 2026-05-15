"""Кликер-ферма: тапы, апгрейды, автокликер, конвертация в гривны.

Экономика:
- 1 тап = `tap_level` cp (стартовый level=1).
- Автокликер: `auto_level × AUTO_RATE` cp/сек, накапливается оффлайн до
  OFFLINE_CAP_HOURS, дальше «ферма засыхает» (не растёт).
- Апгрейды: cost = base × growth^level.
- Конвертация в гривны: 100 cp → 1 гривна. Списывается с банка чата
  (никаких mint из воздуха). Daily cap = 1000 гривен на юзера/чат.
"""
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_bank import ChatBank
from common.models.clicker_farm import ClickerFarm
from common.models.economy_tx import EconomyTx
from common.models.user_balance import UserBalance
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    MarketError,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)

# Параметры (env-tunable)
CP_PER_HRYVNIA = int(os.getenv("CLICKER_CP_PER_HRYVNIA", "100"))  # базовый курс
# Растущий курс: на каждые MINT_RATE_SCALE эмитированных в чате гривен
# курс +1 cp. Тормозит инфляцию — чем больше нафармили, тем дороже cp.
MINT_RATE_SCALE = int(os.getenv("CLICKER_MINT_RATE_SCALE", "10000"))
DAILY_CAP = int(os.getenv("CLICKER_DAILY_CAP", "10000"))        # гривен
OFFLINE_CAP_HOURS = float(os.getenv("CLICKER_OFFLINE_CAP_HOURS", "4"))
AUTO_RATE = float(os.getenv("CLICKER_AUTO_RATE", "0.5"))         # cp/sec на level
TAP_UPGRADE_BASE = int(os.getenv("CLICKER_TAP_UPGRADE_BASE", "50"))
AUTO_UPGRADE_BASE = int(os.getenv("CLICKER_AUTO_UPGRADE_BASE", "200"))
UPGRADE_GROWTH = float(os.getenv("CLICKER_UPGRADE_GROWTH", "1.15"))
MAX_CPS = float(os.getenv("CLICKER_MAX_CPS", "30"))               # серверный rate cap (клиент throttle'ит на 20, это буфер)
MAX_TAP_LEVEL = int(os.getenv("CLICKER_MAX_TAP_LEVEL", "50"))
MAX_AUTO_LEVEL = int(os.getenv("CLICKER_MAX_AUTO_LEVEL", "100"))

# Работницы фермы. rate — cp/сек за уровень; base — цена покупки 1-го уровня,
# далее ×UPGRADE_GROWTH за уровень.
WORKER_TYPES = ["cherry", "lemon", "bell", "star", "diamond"]
WORKER_RATE = {
    "cherry": float(os.getenv("CLICKER_W_CHERRY_RATE", "0.2")),
    "lemon": float(os.getenv("CLICKER_W_LEMON_RATE", "0.5")),
    "bell": float(os.getenv("CLICKER_W_BELL_RATE", "1.5")),
    "star": float(os.getenv("CLICKER_W_STAR_RATE", "5")),
    "diamond": float(os.getenv("CLICKER_W_DIAMOND_RATE", "20")),
}
WORKER_BASE_COST = {
    "cherry": int(os.getenv("CLICKER_W_CHERRY_COST", "50")),
    "lemon": int(os.getenv("CLICKER_W_LEMON_COST", "250")),
    "bell": int(os.getenv("CLICKER_W_BELL_COST", "1200")),
    "star": int(os.getenv("CLICKER_W_STAR_COST", "6000")),
    "diamond": int(os.getenv("CLICKER_W_DIAMOND_COST", "30000")),
}
MAX_WORKER_LEVEL = int(os.getenv("CLICKER_MAX_WORKER_LEVEL", "50"))
# Границы тиров арта по уровню работницы.
WORKER_TIER_T2 = int(os.getenv("CLICKER_WORKER_TIER_T2", "10"))
WORKER_TIER_T3 = int(os.getenv("CLICKER_WORKER_TIER_T3", "25"))


def _worker_tier(level: int) -> int:
    if level <= 0:
        return 0
    if level < WORKER_TIER_T2:
        return 1
    if level < WORKER_TIER_T3:
        return 2
    return 3


def _workers_dict(farm: ClickerFarm) -> dict:
    w = farm.workers or {}
    # нормализуем: только известные типы, int-уровни
    return {t: int(w.get(t, 0) or 0) for t in WORKER_TYPES}


def _worker_next_cost(wtype: str, level: int) -> int:
    """Цена покупки уровня level+1 (с текущего level). level 0 → base."""
    return int(round(WORKER_BASE_COST[wtype] * (UPGRADE_GROWTH ** level)))


def _passive_rate(session, farm: ClickerFarm) -> float:
    """cp/сек = (legacy-работницы по rate×level + гача SR/SSR/UR воркеры)
    × множитель активной героини + legacy автокликер."""
    from services.gacha_service import farm_multipliers

    legacy = sum(WORKER_RATE[t] * lvl for t, lvl in _workers_dict(farm).items())
    gacha_raw, hmult, _h = farm_multipliers(session, farm.user_id, farm.chat_id)
    return (legacy + gacha_raw) * hmult + farm.auto_level * AUTO_RATE


def _heroine_mult(session, farm: ClickerFarm) -> float:
    from services.gacha_service import farm_multipliers

    _p, hmult, _h = farm_multipliers(session, farm.user_id, farm.chat_id)
    return hmult


class ClickerError(MarketError):
    pass


@dataclass
class FarmState:
    cp_balance: int
    tap_level: int
    auto_level: int
    auto_rate_cps: float            # текущая скорость cp/сек
    next_tap_cost: int              # сколько cp стоит следующий апгрейд тапа
    next_auto_cost: int             # сколько cp стоит следующий апгрейд автоклика
    daily_converted: int            # сколько гривен уже вывели сегодня
    daily_cap: int
    daily_remaining: int
    bank_balance: int               # сколько в банке чата (потолок конвертации)
    user_balance: int               # текущий баланс юзера в гривнах
    lifetime_cp: int                # для аналитики
    cp_per_hryvnia: int
    offline_cap_seconds: int
    workers: list                   # [{type, level, tier, rate_cps, next_cost, max}]

    def asdict(self) -> dict:
        return asdict(self)


def _upgrade_cost(base: int, level: int) -> int:
    """level 0 → base, level 1 → base × growth, level N → base × growth^N."""
    return int(round(base * (UPGRADE_GROWTH ** level)))


def _accrue_offline(session, farm: ClickerFarm, now: datetime) -> int:
    """Накопить оффлайн-доход (гача + legacy авто) с last_seen_at,
    но не более OFFLINE_CAP."""
    rate = _passive_rate(session, farm)
    if rate <= 0:
        farm.last_seen_at = now
        return 0
    elapsed = (now - farm.last_seen_at).total_seconds()
    capped = min(elapsed, OFFLINE_CAP_HOURS * 3600)
    income = int(capped * rate)
    if income > 0:
        farm.cp_balance += income
        farm.lifetime_cp += income
    farm.last_seen_at = now
    return income


def _reset_daily_if_needed(farm: ClickerFarm, now: datetime) -> None:
    if (now - farm.daily_window_start).total_seconds() >= 86400:
        farm.daily_window_start = now
        farm.daily_converted = 0


def _total_minted(session, chat_id: int) -> int:
    """Сумма всех эмитированных гривен в чате (kind=clicker_mint)."""
    return int(
        session.query(func.coalesce(func.sum(EconomyTx.amount), 0))
        .filter(EconomyTx.chat_id == chat_id, EconomyTx.kind == "clicker_mint")
        .scalar()
        or 0
    )


def _current_rate(session, chat_id: int) -> int:
    """Растущий курс: base + total_minted // scale."""
    return CP_PER_HRYVNIA + _total_minted(session, chat_id) // MINT_RATE_SCALE


def _to_state(session, farm: ClickerFarm, bank: ChatBank, user_bal: UserBalance) -> FarmState:
    return FarmState(
        cp_balance=int(farm.cp_balance),
        tap_level=int(farm.tap_level),
        auto_level=int(farm.auto_level),
        auto_rate_cps=round(_passive_rate(session, farm), 3),
        next_tap_cost=_upgrade_cost(TAP_UPGRADE_BASE, farm.tap_level - 1) if farm.tap_level < MAX_TAP_LEVEL else 0,
        next_auto_cost=_upgrade_cost(AUTO_UPGRADE_BASE, farm.auto_level) if farm.auto_level < MAX_AUTO_LEVEL else 0,
        daily_converted=int(farm.daily_converted),
        daily_cap=DAILY_CAP,
        daily_remaining=max(0, DAILY_CAP - int(farm.daily_converted)),
        bank_balance=int(bank.balance),
        user_balance=int(user_bal.balance),
        lifetime_cp=int(farm.lifetime_cp),
        cp_per_hryvnia=_current_rate(session, farm.chat_id),
        offline_cap_seconds=int(OFFLINE_CAP_HOURS * 3600),
        workers=[
            {
                "type": t,
                "level": lvl,
                "tier": _worker_tier(lvl),
                "rate_cps": round(WORKER_RATE[t] * lvl, 3),
                "per_level_cps": WORKER_RATE[t],
                "next_cost": _worker_next_cost(t, lvl) if lvl < MAX_WORKER_LEVEL else 0,
                "max": MAX_WORKER_LEVEL,
            }
            for t, lvl in _workers_dict(farm).items()
        ],
    )


def _get_or_create_farm(session, user_id: int, chat_id: int) -> ClickerFarm:
    row = (
        session.query(ClickerFarm)
        .filter(ClickerFarm.user_id == user_id, ClickerFarm.chat_id == chat_id)
        .with_for_update()
        .first()
    )
    if not row:
        row = ClickerFarm(user_id=user_id, chat_id=chat_id)
        session.add(row)
        session.flush()
    # Ленивая конвертация старых работниц в гача-коллекцию (один раз).
    from services.gacha_service import ensure_migrated

    ensure_migrated(session, row)
    return row


def get_state_sync(user_id: int, chat_id: int) -> FarmState:
    """Возвращает текущее состояние с учётом offline-дохода. Сохраняет last_seen_at."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        _reset_daily_if_needed(farm, now)
        farm.updated_at = now
        bank = _get_or_create_bank(session, chat_id)
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def tap_sync(user_id: int, chat_id: int, count: int, elapsed_ms: int) -> FarmState:
    """Серверный rate-limit: реальный yield = min(count, MAX_CPS × elapsed_ms/1000)."""
    if count <= 0:
        raise InvalidArgument("count > 0")
    if elapsed_ms <= 0:
        elapsed_ms = 100
    # серверный кэп: не больше MAX_CPS за elapsed
    max_allowed = max(1, int(MAX_CPS * elapsed_ms / 1000))
    accepted = min(count, max_allowed)

    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        _reset_daily_if_needed(farm, now)
        gain = int(accepted * farm.tap_level * _heroine_mult(session, farm))
        farm.cp_balance += gain
        farm.lifetime_cp += gain
        farm.updated_at = now
        bank = _get_or_create_bank(session, chat_id)
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_tap_sync(user_id: int, chat_id: int) -> FarmState:
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        if farm.tap_level >= MAX_TAP_LEVEL:
            raise InvalidArgument(f"Тап на максимуме (level {MAX_TAP_LEVEL})")
        cost = _upgrade_cost(TAP_UPGRADE_BASE, farm.tap_level - 1)
        if farm.cp_balance < cost:
            raise InsufficientFunds(f"Нужно {cost} cp, у тебя {farm.cp_balance}")
        farm.cp_balance -= cost
        farm.tap_level += 1
        farm.updated_at = now
        bank = _get_or_create_bank(session, chat_id)
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_auto_sync(user_id: int, chat_id: int) -> FarmState:
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        if farm.auto_level >= MAX_AUTO_LEVEL:
            raise InvalidArgument(f"Автокликер на максимуме (level {MAX_AUTO_LEVEL})")
        cost = _upgrade_cost(AUTO_UPGRADE_BASE, farm.auto_level)
        if farm.cp_balance < cost:
            raise InsufficientFunds(f"Нужно {cost} cp, у тебя {farm.cp_balance}")
        farm.cp_balance -= cost
        farm.auto_level += 1
        farm.updated_at = now
        bank = _get_or_create_bank(session, chat_id)
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def hire_worker_sync(user_id: int, chat_id: int, wtype: str) -> FarmState:
    """Нанять работницу или поднять её уровень на +1."""
    if wtype not in WORKER_TYPES:
        raise InvalidArgument(f"Неизвестная работница: {wtype}")
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        workers = _workers_dict(farm)
        level = workers.get(wtype, 0)
        if level >= MAX_WORKER_LEVEL:
            raise InvalidArgument(f"Работница на максимуме (level {MAX_WORKER_LEVEL})")
        cost = _worker_next_cost(wtype, level)
        if farm.cp_balance < cost:
            raise InsufficientFunds(f"Нужно {cost} cp, у тебя {int(farm.cp_balance)}")
        farm.cp_balance -= cost
        workers[wtype] = level + 1
        # JSONB: переприсваиваем dict чтобы SQLAlchemy заметил изменение
        farm.workers = dict(workers)
        farm.updated_at = now
        bank = _get_or_create_bank(session, chat_id)
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def convert_sync(user_id: int, chat_id: int, hryvnia_amount: int) -> FarmState:
    """Списать cp = hryvnia × 100, списать гривны с банка чата, начислить юзеру."""
    if hryvnia_amount <= 0:
        raise InvalidArgument("Сумма должна быть > 0")
    session = SessionLocal()
    try:
        now = datetime.utcnow()
        farm = _get_or_create_farm(session, user_id, chat_id)
        _accrue_offline(session, farm, now)
        _reset_daily_if_needed(farm, now)

        remaining = DAILY_CAP - farm.daily_converted
        if hryvnia_amount > remaining:
            raise InvalidArgument(
                f"Дневной кэп: можешь вывести ещё {remaining} гривен сегодня"
            )

        rate = _current_rate(session, chat_id)
        cp_cost = hryvnia_amount * rate
        if farm.cp_balance < cp_cost:
            raise InsufficientFunds(
                f"Нужно {cp_cost} cp (курс {rate} cp/гривна), у тебя {farm.cp_balance}"
            )

        # Эмиссия: гривны создаются (не из банка чата) — приток в экономику.
        farm.cp_balance -= cp_cost
        farm.daily_converted += hryvnia_amount
        farm.updated_at = now
        user_bal = _get_or_create_balance(session, user_id, chat_id)
        user_bal.balance += hryvnia_amount
        user_bal.updated_at = now
        bank = _get_or_create_bank(session, chat_id)  # только для отображения в стейте

        _log_tx(session, user_id, chat_id, hryvnia_amount,
                kind="clicker_mint",
                note=f"{cp_cost} cp -> {hryvnia_amount} hryvnia (эмиссия)")

        state = _to_state(session, farm, bank, user_bal)
        session.commit()
        return state
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
