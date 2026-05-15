"""Гача-ядро фермы: ролл, pity, rate-up баннер, dedupe→звёзды,
миграция старых работниц, пересчёт дохода фермы.

Доход фермы = Σ (worker.base_value × star_mult) по собранным
worker-персонажам, умноженный на множитель активной героини.
"""
import math
import os
import secrets
from datetime import datetime

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting
from common.models.clicker_farm import ClickerFarm
from common.models.gacha_collection import GachaCollection
from services.gacha_catalog import (
    BY_RARITY,
    CATALOG,
    DEFAULT_HEROINE_MULT,
    LEGACY_WORKER_MAP,
    star_mult,
)
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)
_rng = secrets.SystemRandom()

ROLL_COST = int(os.getenv("GACHA_ROLL_COST", "300"))
X10_COST = int(os.getenv("GACHA_X10_COST", str(ROLL_COST * 9)))  # скидка ~1 крутка
SSR_PITY = int(os.getenv("GACHA_SSR_PITY", "50"))
UR_PITY = int(os.getenv("GACHA_UR_PITY", "90"))
BANNER_RATEUP = float(os.getenv("GACHA_BANNER_RATEUP", "0.5"))  # доля баннерного среди UR
# Из ролла исключён R — legacy-работницы (cherry..diamond) остаются
# отдельной системой (доход по level), гача даёт только SR/SSR/UR поверх.
BASE_WEIGHTS = {"SR": 0.80, "SSR": 0.18, "UR": 0.02}
# Возврат гривнами за дубль 5★ (по редкости)
DUP_REFUND = {"R": 20, "SR": 80, "SSR": 300, "UR": 1500}

_BANNER_KEY = "gacha_banner"


def _ensure_bs_table() -> None:
    from common.db.db import engine

    BotSetting.__table__.create(bind=engine, checkfirst=True)


def get_banner() -> str:
    """char_id текущего rate-up UR. По умолчанию первый UR каталога."""
    _ensure_bs_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == _BANNER_KEY).first()
        if row and row.value in CATALOG and CATALOG[row.value].rarity == "UR":
            return row.value
    finally:
        s.close()
    return BY_RARITY["UR"][0]


def set_banner(char_id: str) -> None:
    if char_id not in CATALOG or CATALOG[char_id].rarity != "UR":
        raise InvalidArgument("Баннер должен быть UR-персонажем")
    _ensure_bs_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == _BANNER_KEY).first()
        if row:
            row.value = char_id
        else:
            s.add(BotSetting(key=_BANNER_KEY, value=char_id))
        s.commit()
    finally:
        s.close()


def _grant(session, user_id: int, chat_id: int, char_id: str) -> dict:
    """Выдать персонажа: новый → 1★, дубль → +1★ (макс 5), сверх → возврат."""
    row = (
        session.query(GachaCollection)
        .filter(
            GachaCollection.user_id == user_id,
            GachaCollection.chat_id == chat_id,
            GachaCollection.char_id == char_id,
        )
        .with_for_update()
        .first()
    )
    rarity = CATALOG[char_id].rarity
    if row is None:
        session.add(GachaCollection(
            user_id=user_id, chat_id=chat_id, char_id=char_id, stars=1, copies=1
        ))
        # flush, чтобы повторное выпадение того же чара в x10 нашло запись
        # (иначе второй add → UniqueViolation на commit).
        session.flush()
        return {"char_id": char_id, "rarity": rarity, "stars": 1, "new": True, "refund": 0}
    row.copies += 1
    if row.stars < 5:
        row.stars += 1
        return {"char_id": char_id, "rarity": rarity, "stars": row.stars,
                "new": False, "refund": 0}
    # уже 5★ — возврат гривнами
    refund = DUP_REFUND.get(rarity, 0)
    return {"char_id": char_id, "rarity": rarity, "stars": 5,
            "new": False, "refund": refund}


def _pick_rarity(farm: ClickerFarm) -> str:
    farm.pity_ssr += 1
    farm.pity_ur += 1
    if farm.pity_ur >= UR_PITY:
        return "UR"
    if farm.pity_ssr >= SSR_PITY:
        return "SSR"
    x = _rng.random()
    acc = 0.0
    for r in ("UR", "SSR", "SR"):
        acc += BASE_WEIGHTS[r]
        if x < acc:
            return r
    return "SR"


def _pick_char(rarity: str) -> str:
    if rarity == "UR":
        banner = get_banner()
        if _rng.random() < BANNER_RATEUP:
            return banner
        return _rng.choice(BY_RARITY["UR"])
    return _rng.choice(BY_RARITY[rarity])


def _apply_pity_reset(farm: ClickerFarm, rarity: str) -> None:
    if rarity == "UR":
        farm.pity_ur = 0
        farm.pity_ssr = 0
    elif rarity == "SSR":
        farm.pity_ssr = 0


def ensure_migrated(session, farm: ClickerFarm) -> None:
    """Legacy-работницы (cherry..diamond в farm.workers) НЕ конвертируются:
    они продолжают приносить доход по старой формуле rate×level, чтобы
    прогресс не обнулялся. Гача — отдельный слой SR/SSR/UR поверх.
    Старые ошибочно созданные R-записи удаляем (иначе двойной счёт)."""
    if farm.gacha_migrated:
        return
    legacy_r = list(LEGACY_WORKER_MAP.values())
    if legacy_r:
        session.query(GachaCollection).filter(
            GachaCollection.user_id == farm.user_id,
            GachaCollection.chat_id == farm.chat_id,
            GachaCollection.char_id.in_(legacy_r),
        ).delete(synchronize_session=False)
    farm.gacha_migrated = 1


def farm_multipliers(session, user_id: int, chat_id: int) -> tuple[float, float, str | None]:
    """(gacha_worker_raw, heroine_mult, active_heroine_char_id).

    gacha_worker_raw — Σ base_value × star_mult по SR/SSR/UR-воркерам
    (БЕЗ R: legacy-работницы считаются отдельно в clicker_service по
    старой формуле). Множитель героини применяет уже caller.
    """
    rows = (
        session.query(GachaCollection)
        .filter(
            GachaCollection.user_id == user_id,
            GachaCollection.chat_id == chat_id,
        )
        .all()
    )
    owned = {r.char_id: r for r in rows}
    worker_sum = 0.0
    for cid, rec in owned.items():
        c = CATALOG.get(cid)
        if c and c.role == "worker" and c.rarity != "R":
            worker_sum += c.base_value * star_mult(rec.stars)

    farm = (
        session.query(ClickerFarm)
        .filter(ClickerFarm.user_id == user_id, ClickerFarm.chat_id == chat_id)
        .first()
    )
    heroine_mult = DEFAULT_HEROINE_MULT
    active = farm.active_heroine if farm else None
    if active and active in owned:
        hc = CATALOG.get(active)
        if hc and hc.role == "heroine":
            heroine_mult = hc.base_value * star_mult(owned[active].stars)
        else:
            active = None
    else:
        active = None
    return worker_sum, heroine_mult, active


# ---------------- public sync ops ----------------


def roll_sync(user_id: int, chat_id: int, count: int) -> dict:
    if count not in (1, 10):
        raise InvalidArgument("count: 1 или 10")
    price = ROLL_COST if count == 1 else X10_COST
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        ensure_migrated(session, farm)
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < price:
            raise InsufficientFunds(f"Нужно {price}, у тебя {bal.balance}")
        bank = _get_or_create_bank(session, chat_id)
        now = datetime.utcnow()
        bal.balance -= price
        bal.updated_at = now
        bank.balance += price
        bank.updated_at = now
        _log_tx(session, user_id, chat_id, -price, kind="gacha_roll",
                note=f"x{count}")
        _log_tx(session, None, chat_id, price, kind="gacha_roll_to_bank")

        results = []
        best_rarity_idx = -1
        order = ["R", "SR", "SSR", "UR"]
        for _ in range(count):
            rarity = _pick_rarity(farm)
            char_id = _pick_char(rarity)
            _apply_pity_reset(farm, rarity)
            g = _grant(session, user_id, chat_id, char_id)
            results.append(g)
            best_rarity_idx = max(best_rarity_idx, order.index(rarity))

        # x10 гарант SR+: если всё R — апгрейдим последний до случайного SR
        if count == 10 and best_rarity_idx < 1:
            cid = _rng.choice(BY_RARITY["SR"])
            results[-1] = _grant(session, user_id, chat_id, cid)

        total_refund = sum(r["refund"] for r in results)
        if total_refund > 0:
            bal.balance += total_refund
            _log_tx(session, user_id, chat_id, total_refund,
                    kind="gacha_dup_refund", note="дубли 5★")

        farm.gacha_rolls += count
        farm.updated_at = now
        out = {
            "results": [
                {
                    "char_id": r["char_id"],
                    "name": CATALOG[r["char_id"]].name,
                    "rarity": r["rarity"],
                    "stars": r["stars"],
                    "new": r["new"],
                    "refund": r["refund"],
                    "asset": CATALOG[r["char_id"]].asset,
                }
                for r in results
            ],
            "spent": price,
            "refunded": total_refund,
            "pity_ssr": farm.pity_ssr,
            "pity_ur": farm.pity_ur,
            "user_balance": bal.balance,
        }
        session.commit()
        return out
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def collection_sync(user_id: int, chat_id: int) -> dict:
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        ensure_migrated(session, farm)
        rows = (
            session.query(GachaCollection)
            .filter(
                GachaCollection.user_id == user_id,
                GachaCollection.chat_id == chat_id,
            )
            .all()
        )
        owned = {r.char_id: r for r in rows}
        items = []
        for cid, c in CATALOG.items():
            rec = owned.get(cid)
            items.append({
                "char_id": cid,
                "name": c.name,
                "rarity": c.rarity,
                "role": c.role,
                "asset": c.asset,
                "owned": rec is not None,
                "stars": rec.stars if rec else 0,
                "base_value": c.base_value,
            })
        out = {
            "items": items,
            "active_heroine": farm.active_heroine,
            "banner": get_banner(),
            "pity_ssr": farm.pity_ssr,
            "pity_ur": farm.pity_ur,
            "ssr_pity": SSR_PITY,
            "ur_pity": UR_PITY,
            "roll_cost": ROLL_COST,
            "x10_cost": X10_COST,
            "gacha_rolls": farm.gacha_rolls,
        }
        session.commit()
        return out
    finally:
        session.close()


def set_heroine_sync(user_id: int, chat_id: int, char_id: str) -> dict:
    if char_id not in CATALOG or CATALOG[char_id].role != "heroine":
        raise InvalidArgument("Это не героиня")
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        owns = (
            session.query(GachaCollection)
            .filter(
                GachaCollection.user_id == user_id,
                GachaCollection.chat_id == chat_id,
                GachaCollection.char_id == char_id,
            )
            .first()
        )
        if not owns:
            raise InvalidArgument("Этой героини нет в коллекции")
        farm = _get_or_create_farm(session, user_id, chat_id)
        farm.active_heroine = char_id
        farm.updated_at = datetime.utcnow()
        session.commit()
        return {"active_heroine": char_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
