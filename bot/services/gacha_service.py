"""Гача-ядро фермы: ролл, pity, rate-up баннер, dedupe→звёзды,
миграция старых работниц, пересчёт дохода фермы.

Доход фермы = Σ (worker.base_value × star_mult) по собранным
worker-персонажам, умноженный на множитель активной героини.
"""
import math
import os
import secrets
from datetime import datetime, timedelta

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting
from common.models.clicker_farm import ClickerFarm
from common.models.gacha_collection import GachaCollection
from common.models.gacha_roll_log import GachaRollLog
from services.gacha_catalog import (
    BY_RARITY,
    CATALOG,
    DEFAULT_HEROINE_MULT,
    LEGACY_WORKER_MAP,
    card_ability,
    card_position,
    card_power,
    card_stats,
    level_cap,
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
X10_COST = int(os.getenv("GACHA_X10_COST", str(ROLL_COST * 9)))  # legacy (v1), не используется в v2-крутке
SSR_PITY = int(os.getenv("GACHA_SSR_PITY", "50"))
UR_PITY = int(os.getenv("GACHA_UR_PITY", "90"))   # = HARD_PITY (гарант UR)
HARD_PITY = UR_PITY
SOFT_PITY_START = int(os.getenv("GACHA_SOFT_PITY", "75"))  # с этого счётчика растёт шанс UR
BANNER_RATEUP = float(os.getenv("GACHA_BANNER_RATEUP", "0.5"))  # 50/50 баннерный среди UR
# Из ролла исключён R — legacy-работницы (cherry..diamond) остаются
# отдельной системой (доход по level), гача даёт только SR/SSR/UR поверх.
BASE_WEIGHTS = {"SR": 0.80, "SSR": 0.18, "UR": 0.02}
UR_BASE_RATE = BASE_WEIGHTS["UR"]
# Возврат гривнами за дубль 5★ (по редкости) — legacy v1.
DUP_REFUND = {"R": 20, "SR": 80, "SSR": 300, "UR": 1500}

# --- v2: валюта gems + экономика крутки (docs/gacha_v2.md, открытые параметры) ---
CP_PER_GEM = int(os.getenv("GACHA_CP_PER_GEM", "300"))   # цена 1 gem в cp (через ферму/AMM)
ROLL_GEMS = int(os.getenv("GACHA_ROLL_GEMS", "1"))       # x1 крутка
X10_GEMS = int(os.getenv("GACHA_X10_GEMS", "9"))         # x10 (скидка ~1 крутка)
DAILY_GEMS = int(os.getenv("GACHA_DAILY_GEMS", "1"))     # ежедневный бонус в gems
# Возврат gems за дубль 5★ (закрытый цикл крутка↔дубль).
DUP_REFUND_GEMS = {"R": 0, "SR": 0, "SSR": 1, "UR": 5}

TEAM_SIZE = 5  # размер боевого состава

# --- v2: уровень/опыт карт ---
EXP_BASE = int(os.getenv("GACHA_EXP_BASE", "50"))        # стоимость уровня L = EXP_BASE * L
PVP_WIN_EXP = int(os.getenv("GACHA_PVP_WIN_EXP", "120"))
PVP_LOSS_EXP = int(os.getenv("GACHA_PVP_LOSS_EXP", "45"))

# Ежедневный бонус: одна выдача в сутки (UTC-календарный день).
DAILY_BONUS = int(os.getenv("GACHA_DAILY_BONUS", str(ROLL_COST)))  # legacy v1
# Длительность баннера в днях (для обратного отсчёта в UI).
BANNER_DAYS = int(os.getenv("GACHA_BANNER_DAYS", "7"))
# «Приласкать»: фразы героинь (cosmetic) + сколько привязанности за 1 bond-уровень.
AFFECTION_PER_BOND = 10
PET_LINES = [
    "Скучала по тебе ♥",
    "Опять ты~ непоседа",
    "Покрутишь ещё разок?",
    "Ммм… нежнее.",
    "Ты сегодня в ударе!",
    "Я только твоя.",
    "Готова к призыву~",
]

_BANNER_KEY = "gacha_banner"
_BANNER_UNTIL_KEY = "gacha_banner_until"


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


def get_banner_until() -> str | None:
    """ISO-время окончания текущего баннера (UTC) или None, если не задано."""
    _ensure_bs_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == _BANNER_UNTIL_KEY).first()
        return row.value if row else None
    finally:
        s.close()


def _upsert_setting(s, key: str, value: str) -> None:
    row = s.query(BotSetting).filter(BotSetting.key == key).first()
    if row:
        row.value = value
    else:
        s.add(BotSetting(key=key, value=value))


def set_banner(char_id: str, days: int = BANNER_DAYS) -> None:
    if char_id not in CATALOG or CATALOG[char_id].rarity != "UR":
        raise InvalidArgument("Баннер должен быть UR-персонажем")
    _ensure_bs_table()
    until = (datetime.utcnow() + timedelta(days=days)).isoformat()
    s = SessionLocal()
    try:
        _upsert_setting(s, _BANNER_KEY, char_id)
        _upsert_setting(s, _BANNER_UNTIL_KEY, until)
        s.commit()
    finally:
        s.close()


def rarity_rates() -> dict:
    """Отображаемые шансы крутки в процентах (R из гачи исключён)."""
    return {r: round(w * 100, 1) for r, w in BASE_WEIGHTS.items()}


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
    # уже 5★ — возврат gems (закрытый цикл крутка↔дубль)
    refund = DUP_REFUND_GEMS.get(rarity, 0)
    return {"char_id": char_id, "rarity": rarity, "stars": 5,
            "new": False, "refund": refund}


def _ur_chance(pity_ur: int) -> float:
    """mihoyo soft pity: базовый шанс до SOFT_PITY_START, дальше линейный
    рост до 1.0 на HARD_PITY."""
    if pity_ur >= HARD_PITY:
        return 1.0
    if pity_ur < SOFT_PITY_START:
        return UR_BASE_RATE
    span = max(1, HARD_PITY - SOFT_PITY_START)
    t = (pity_ur - SOFT_PITY_START + 1) / span
    return min(1.0, UR_BASE_RATE + (1.0 - UR_BASE_RATE) * t)


def _do_pull(farm: ClickerFarm) -> dict:
    """Одна крутка: mihoyo-pity (soft/hard UR + SSR-гарант) + rate-up 50/50
    с гарантом следующего UR баннерным. Мутирует pity-счётчики/флаг на farm,
    возвращает результат + телеметрию."""
    farm.pity_ssr += 1
    farm.pity_ur += 1
    pity_ssr_at, pity_ur_at = farm.pity_ssr, farm.pity_ur
    soft = hard = False

    if farm.pity_ur >= HARD_PITY:
        hard = True
        rarity = "UR"
    elif _rng.random() < _ur_chance(farm.pity_ur):
        rarity = "UR"
        soft = farm.pity_ur >= SOFT_PITY_START
    elif farm.pity_ssr >= SSR_PITY:
        rarity = "SSR"
    else:
        ssr_share = BASE_WEIGHTS["SSR"] / (BASE_WEIGHTS["SSR"] + BASE_WEIGHTS["SR"])
        rarity = "SSR" if _rng.random() < ssr_share else "SR"

    rate_up_win = False
    if rarity == "UR":
        banner = get_banner()
        if farm.rate_up_lost:
            char_id, rate_up_win = banner, True
            farm.rate_up_lost = 0
        elif _rng.random() < BANNER_RATEUP:
            char_id, rate_up_win = banner, True
        else:
            others = [c for c in BY_RARITY["UR"] if c != banner] or BY_RARITY["UR"]
            char_id = _rng.choice(others)
            farm.rate_up_lost = 1  # увели — следующий UR гарантированно баннерный
    else:
        char_id = _rng.choice(BY_RARITY[rarity])

    if rarity == "UR":
        farm.pity_ur = 0
        farm.pity_ssr = 0
    elif rarity == "SSR":
        farm.pity_ssr = 0

    return {"char_id": char_id, "rarity": rarity, "pity_ssr_at": pity_ssr_at,
            "pity_ur_at": pity_ur_at, "soft": soft, "hard": hard,
            "rate_up_win": rate_up_win}


def _exp_to_next(level: int) -> int:
    return EXP_BASE * max(1, level)


def add_card_exp(row: GachaCollection, amount: int) -> None:
    """Начислить опыт карте с прокачкой уровня (кап по звёздам)."""
    cap = level_cap(row.stars)
    row.exp = (row.exp or 0) + max(0, amount)
    while row.level < cap and row.exp >= _exp_to_next(row.level):
        row.exp -= _exp_to_next(row.level)
        row.level += 1
    if row.level >= cap:
        row.exp = min(row.exp, _exp_to_next(row.level))


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
    price = ROLL_GEMS if count == 1 else X10_GEMS
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        ensure_migrated(session, farm)
        if (farm.gems or 0) < price:
            raise InsufficientFunds(f"Нужно {price} gems, у тебя {farm.gems or 0}")
        now = datetime.utcnow()
        farm.gems = (farm.gems or 0) - price

        results = []
        for _ in range(count):
            pull = _do_pull(farm)
            g = _grant(session, user_id, chat_id, pull["char_id"])
            results.append(g)
            # телеметрия теста (docs/gacha_v2.md)
            session.add(GachaRollLog(
                user_id=user_id, chat_id=chat_id, char_id=pull["char_id"],
                rarity=pull["rarity"], pity_ssr=pull["pity_ssr_at"],
                pity_ur=pull["pity_ur_at"], soft_pity=pull["soft"],
                hard_pity=pull["hard"], rate_up_win=pull["rate_up_win"],
                is_x10=(count == 10), gem_cost=(price if not results[:-1] else 0),
                created_at=now,
            ))

        total_refund = sum(r["refund"] for r in results)  # gems
        if total_refund > 0:
            farm.gems = (farm.gems or 0) + total_refund

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
            "gems": farm.gems,
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
            stars = rec.stars if rec else 0
            level = rec.level if rec else 1
            items.append({
                "char_id": cid,
                "name": c.name,
                "rarity": c.rarity,
                "role": c.role,
                "asset": c.asset,
                "owned": rec is not None,
                "stars": stars,
                "base_value": c.base_value,
                "affection": rec.affection if rec else 0,
                "bond": (rec.affection // AFFECTION_PER_BOND) if rec else 0,
                # v2: ККИ-слой
                "level": level,
                "exp": rec.exp if rec else 0,
                "exp_to_next": _exp_to_next(level),
                "level_cap": level_cap(stars if stars else 1),
                "position": card_position(cid),
                "ability": card_ability(cid),
                "stats": card_stats(cid, max(1, stars), level),
                "power": card_power(cid, max(1, stars), level),
            })
        out = {
            "items": items,
            "active_heroine": farm.active_heroine,
            "banner": get_banner(),
            "banner_until": get_banner_until(),
            "pity_ssr": farm.pity_ssr,
            "pity_ur": farm.pity_ur,
            "ssr_pity": SSR_PITY,
            "ur_pity": UR_PITY,
            "soft_pity": SOFT_PITY_START,
            "gacha_rolls": farm.gacha_rolls,
            "rates": rarity_rates(),
            "banner_rateup": round(BANNER_RATEUP * 100),
            "daily_available": _daily_available(farm),
            "team": _team_slots(farm, owned),
            "team_size": TEAM_SIZE,
            # v2: валюта gems
            "gems": farm.gems or 0,
            "cp_balance": int(farm.cp_balance or 0),
            "roll_cost": ROLL_GEMS,
            "x10_cost": X10_GEMS,
            "cp_per_gem": CP_PER_GEM,
            "daily_amount": DAILY_GEMS,
            # PvP
            "pvp_elo": farm.pvp_elo,
            "pvp_wins": farm.pvp_wins,
            "pvp_losses": farm.pvp_losses,
        }
        session.commit()
        return out
    finally:
        session.close()


def _daily_available(farm: ClickerFarm) -> bool:
    """Доступен ли ежедневный бонус (новый UTC-календарный день)."""
    last = farm.last_daily_at
    return last is None or last.date() < datetime.utcnow().date()


def daily_sync(user_id: int, chat_id: int) -> dict:
    """Забрать ежедневный бонус (раз в сутки). Кредитует gems (v2)."""
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        if not _daily_available(farm):
            raise InvalidArgument("Сегодня бонус уже получен")
        now = datetime.utcnow()
        farm.gems = (farm.gems or 0) + DAILY_GEMS
        farm.last_daily_at = now
        farm.updated_at = now
        session.commit()
        return {
            "claimed": True,
            "amount": DAILY_GEMS,
            "gems": farm.gems,
            "daily_available": False,
        }
    finally:
        session.close()


def buy_gems_sync(user_id: int, chat_id: int, gems: int) -> dict:
    """Купить gems за cp фермы (по курсу CP_PER_GEM). docs/gacha_v2.md."""
    gems = int(gems)
    if gems <= 0:
        raise InvalidArgument("gems: положительное число")
    cost_cp = gems * CP_PER_GEM
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        if int(farm.cp_balance or 0) < cost_cp:
            raise InsufficientFunds(f"Нужно {cost_cp} cp, у тебя {int(farm.cp_balance or 0)}")
        farm.cp_balance -= cost_cp
        farm.gems = (farm.gems or 0) + gems
        farm.updated_at = datetime.utcnow()
        session.commit()
        return {
            "bought": gems,
            "spent_cp": cost_cp,
            "gems": farm.gems,
            "cp_balance": int(farm.cp_balance),
        }
    finally:
        session.close()


def pet_sync(user_id: int, chat_id: int, char_id: str) -> dict:
    """«Приласкать» собранного персонажа: +1 привязанность, случайная фраза."""
    if char_id not in CATALOG:
        raise InvalidArgument("Нет такого персонажа")
    session = SessionLocal()
    try:
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
        if not row:
            raise InvalidArgument("Этого персонажа нет в коллекции")
        row.affection = (row.affection or 0) + 1
        session.commit()
        return {
            "char_id": char_id,
            "affection": row.affection,
            "bond": row.affection // AFFECTION_PER_BOND,
            "line": _rng.choice(PET_LINES),
        }
    finally:
        session.close()


def _team_slots(farm: ClickerFarm, owned: dict) -> list:
    """Сохранённый состав игрока (валидируется по владению) или авто-топ-5.
    Возвращает [{char_id, row}] длиной до TEAM_SIZE."""
    saved = farm.team if isinstance(farm.team, list) else None
    slots, seen = [], set()
    if saved:
        for s in saved:
            cid = (s or {}).get("char_id")
            row = (s or {}).get("row")
            if cid in owned and cid not in seen and len(slots) < TEAM_SIZE:
                slots.append({"char_id": cid,
                              "row": row if row in ("front", "back") else card_position(cid)})
                seen.add(cid)
    if not slots:
        ordered = sorted(
            owned.values(),
            key=lambda r: card_power(r.char_id, r.stars, r.level),
            reverse=True,
        )[:TEAM_SIZE]
        slots = [{"char_id": r.char_id, "row": card_position(r.char_id)} for r in ordered]
    return slots


def set_team_sync(user_id: int, chat_id: int, slots: list) -> dict:
    """Сохранить боевой состав (до TEAM_SIZE карт + ряд каждой)."""
    if not isinstance(slots, list) or len(slots) > TEAM_SIZE:
        raise InvalidArgument(f"Состав: до {TEAM_SIZE} карт")
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        owned = {
            r.char_id
            for r in session.query(GachaCollection).filter(
                GachaCollection.user_id == user_id,
                GachaCollection.chat_id == chat_id,
            ).all()
        }
        clean, seen = [], set()
        for s in slots:
            cid = (s or {}).get("char_id")
            row = (s or {}).get("row")
            if cid not in CATALOG:
                continue
            if cid not in owned:
                raise InvalidArgument("В составе карта, которой нет в коллекции")
            if cid in seen:
                continue
            clean.append({"char_id": cid,
                          "row": row if row in ("front", "back") else card_position(cid)})
            seen.add(cid)
        if not clean:
            raise InvalidArgument("Добавь в состав хотя бы одну карту")
        farm = _get_or_create_farm(session, user_id, chat_id)
        farm.team = clean
        farm.updated_at = datetime.utcnow()
        session.commit()
        return {"team": clean}
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
