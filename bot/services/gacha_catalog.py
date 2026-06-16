"""Каталог гача-персонажей фермы (фиксирован в коде).

role:
  worker  — даёт пассивный cp/сек (base_value × звёздный множитель)
  heroine — ставится в центр фермы, даёт глобальный множитель к доходу
            и тапу (mult, растёт со звёздами)

rarity: R / SR / SSR / UR. asset — файл в miniapp/static/gacha/<id>.png
(для R переиспользуем существующие farm/<type>_t1.png).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class GachaChar:
    id: str
    name: str
    rarity: str          # R | SR | SSR | UR
    role: str            # worker | heroine
    base_value: float    # worker: cp/сек за 1★; heroine: базовый множитель (1.x)
    asset: str           # путь к картинке


# Звёздный множитель: 1★=1.0, каждая следующая +0.25 (5★ = 2.0)
def star_mult(stars: int) -> float:
    return 1.0 + 0.25 * max(0, min(stars, 5) - 1)


CATALOG: dict[str, GachaChar] = {}


def _add(c: GachaChar) -> None:
    CATALOG[c.id] = c


# ---- R: базовые работницы ----
# arts: новые webp из дизайн-сборки (раньше переиспользовали farm-тайлы).
_add(GachaChar("r_cherry", "Вишнёвая", "R", "worker", 0.2, "/gacha/r_cherry.webp"))
_add(GachaChar("r_lemon", "Лимонная", "R", "worker", 0.5, "/gacha/r_lemon.webp"))
_add(GachaChar("r_bell", "Колокольчик", "R", "worker", 1.0, "/gacha/r_bell.webp"))
_add(GachaChar("r_star", "Звёздная", "R", "worker", 2.0, "/gacha/r_star.webp"))
_add(GachaChar("r_diamond", "Бриллиантовая", "R", "worker", 4.0, "/gacha/r_diamond.webp"))

# ---- SR: усиленные работницы ----
_add(GachaChar("sr_harvest", "Жница", "SR", "worker", 8.0, "/gacha/sr_harvest.webp"))
_add(GachaChar("sr_herbalist", "Травница", "SR", "worker", 10.0, "/gacha/sr_herbalist.webp"))
_add(GachaChar("sr_beekeeper", "Пасечница", "SR", "worker", 13.0, "/gacha/sr_beekeeper.webp"))
_add(GachaChar("sr_autumn", "Осенняя", "SR", "worker", 16.0, "/gacha/sr_autumn.webp"))

# ---- SSR: сильные работницы + героиня ----
_add(GachaChar("ssr_noble", "Дворянка полей", "SSR", "worker", 35.0, "/gacha/ssr_noble.webp"))
_add(GachaChar("ssr_orchard", "Принцесса садов", "SSR", "worker", 45.0, "/gacha/ssr_orchard.webp"))
_add(GachaChar("ssr_sun", "Солнечная богиня", "SSR", "heroine", 1.5, "/gacha/ssr_sun.webp"))

# ---- UR: легендарные героини (центр фермы) ----
_add(GachaChar("ur_celestial", "Небесная жница", "UR", "heroine", 2.0, "/gacha/ur_celestial.webp"))
_add(GachaChar("ur_cosmic", "Космическая королева", "UR", "heroine", 2.5, "/gacha/ur_cosmic.webp"))
_add(GachaChar("ur_phoenix", "Дева-феникс", "UR", "heroine", 3.0, "/gacha/ur_phoenix.webp"))

# Базовая героиня по умолчанию (если ни одна не выбрана) — старая главная.
DEFAULT_HEROINE_MULT = 1.0
DEFAULT_HEROINE_ASSET = "/farm/heroine_idle.png"

RARITIES = ["R", "SR", "SSR", "UR"]
BY_RARITY: dict[str, list[str]] = {r: [] for r in RARITIES}
for _c in CATALOG.values():
    BY_RARITY[_c.rarity].append(_c.id)

# Старые типы работниц → R-персонаж (для миграции)
LEGACY_WORKER_MAP = {
    "cherry": "r_cherry",
    "lemon": "r_lemon",
    "bell": "r_bell",
    "star": "r_star",
    "diamond": "r_diamond",
}

# ============================================================================
# v2: боевые статы карт (ККИ-слой). Каталог — в коде, как и фермовый.
# Доку: docs/gacha_v2.md. Числа — «открытые параметры», крутятся на тесте.
# ============================================================================

MAX_LEVEL = 60
# Кап уровня по звёздам (5★ снимает потолок до MAX_LEVEL).
LEVEL_CAP_BY_STAR = {1: 20, 2: 30, 3: 40, 4: 50, 5: MAX_LEVEL}
STAR_STAT_BONUS = 0.08   # +8% ко всем статам за звезду сверх первой
LEVEL_STAT_GROWTH = 0.03  # +3% за уровень сверх первого

# Базовые статы по тиру (для front-роли; back модифицируется ниже).
TIER_BASE = {
    "R":   {"hp": 300,  "atk": 45,  "def": 25, "spd": 50},
    "SR":  {"hp": 480,  "atk": 70,  "def": 38, "spd": 58},
    "SSR": {"hp": 720,  "atk": 105, "def": 55, "spd": 66},
    "UR":  {"hp": 1050, "atk": 150, "def": 78, "spd": 75},
}

# Способности (effect_data — простые множители; читает battle_service).
ABILITIES = {
    "heavy_strike": {"name": "Тяжёлый удар", "desc": "×1.8 урон по цели",      "type": "single", "mult": 1.8},
    "crit":         {"name": "Критический",  "desc": "×1.6 урон по цели",      "type": "single", "mult": 1.6},
    "aoe":          {"name": "Залп",         "desc": "×0.6 урон по всем врагам", "type": "aoe",   "mult": 0.6},
    "heal":         {"name": "Исцеление",    "desc": "лечит союзника на 22% HP", "type": "heal",  "frac": 0.22},
    "guard":        {"name": "Защита",       "desc": "лечит себя на 16% HP",     "type": "self_heal", "frac": 0.16},
}
EVERY_N_ACTIONS = 3  # абилка срабатывает на каждое N-е действие карты

# Позиция (front принимает удар первым) и способность по персонажу.
CARD_POSITION = {
    "r_cherry": "front", "r_lemon": "back", "r_bell": "back",
    "r_star": "back", "r_diamond": "front",
    "sr_harvest": "front", "sr_herbalist": "back",
    "sr_beekeeper": "front", "sr_autumn": "back",
    "ssr_noble": "front", "ssr_orchard": "back", "ssr_sun": "back",
    "ur_celestial": "back", "ur_cosmic": "front", "ur_phoenix": "back",
}
CARD_ABILITY = {
    "r_cherry": "guard", "r_lemon": "crit", "r_bell": "crit",
    "r_star": "heavy_strike", "r_diamond": "guard",
    "sr_harvest": "heavy_strike", "sr_herbalist": "heal",
    "sr_beekeeper": "guard", "sr_autumn": "aoe",
    "ssr_noble": "heavy_strike", "ssr_orchard": "aoe", "ssr_sun": "heal",
    "ur_celestial": "heal", "ur_cosmic": "heavy_strike", "ur_phoenix": "aoe",
}


def card_position(char_id: str) -> str:
    return CARD_POSITION.get(char_id, "back")


def card_ability(char_id: str) -> str:
    return CARD_ABILITY.get(char_id, "crit")


def level_cap(stars: int) -> int:
    return LEVEL_CAP_BY_STAR.get(max(1, min(stars, 5)), MAX_LEVEL)


def card_stats(char_id: str, stars: int, level: int) -> dict:
    """Боевые статы карты с учётом тира, роли (front/back), звёзд и уровня."""
    c = CATALOG[char_id]
    base = dict(TIER_BASE[c.rarity])
    pos = card_position(char_id)
    if pos == "front":
        base["hp"] = base["hp"] * 1.3
        base["def"] = base["def"] * 1.3
        base["atk"] = base["atk"] * 0.85
    else:  # back — урон
        base["atk"] = base["atk"] * 1.25
        base["hp"] = base["hp"] * 0.85
    star_m = 1.0 + STAR_STAT_BONUS * (max(1, min(stars, 5)) - 1)
    lvl_m = 1.0 + LEVEL_STAT_GROWTH * (max(1, level) - 1)
    m = star_m * lvl_m
    return {k: int(round(v * m)) for k, v in base.items()}


def card_power(char_id: str, stars: int, level: int) -> int:
    """Скалярная сила карты — для авто-сборки команды и сортировок."""
    s = card_stats(char_id, stars, level)
    return s["hp"] + s["atk"] * 6 + s["def"] * 4 + s["spd"] * 3
