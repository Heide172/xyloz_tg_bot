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


# ---- R: базовые работницы (переиспользуем farm-ассеты) ----
_add(GachaChar("r_cherry", "Вишнёвая", "R", "worker", 0.2, "/farm/cherry_t1.png"))
_add(GachaChar("r_lemon", "Лимонная", "R", "worker", 0.5, "/farm/lemon_t1.png"))
_add(GachaChar("r_bell", "Колокольчик", "R", "worker", 1.0, "/farm/bell_t1.png"))
_add(GachaChar("r_star", "Звёздная", "R", "worker", 2.0, "/farm/star_t1.png"))
_add(GachaChar("r_diamond", "Бриллиантовая", "R", "worker", 4.0, "/farm/diamond_t1.png"))

# ---- SR: усиленные работницы ----
_add(GachaChar("sr_harvest", "Жница", "SR", "worker", 8.0, "/gacha/sr_harvest.png"))
_add(GachaChar("sr_herbalist", "Травница", "SR", "worker", 10.0, "/gacha/sr_herbalist.png"))
_add(GachaChar("sr_beekeeper", "Пасечница", "SR", "worker", 13.0, "/gacha/sr_beekeeper.png"))
_add(GachaChar("sr_autumn", "Осенняя", "SR", "worker", 16.0, "/gacha/sr_autumn.png"))

# ---- SSR: сильные работницы + героиня ----
_add(GachaChar("ssr_noble", "Дворянка полей", "SSR", "worker", 35.0, "/gacha/ssr_noble.png"))
_add(GachaChar("ssr_orchard", "Принцесса садов", "SSR", "worker", 45.0, "/gacha/ssr_orchard.png"))
_add(GachaChar("ssr_sun", "Солнечная богиня", "SSR", "heroine", 1.5, "/gacha/ssr_sun.png"))

# ---- UR: легендарные героини (центр фермы) ----
_add(GachaChar("ur_celestial", "Небесная жница", "UR", "heroine", 2.0, "/gacha/ur_celestial.png"))
_add(GachaChar("ur_cosmic", "Космическая королева", "UR", "heroine", 2.5, "/gacha/ur_cosmic.png"))
_add(GachaChar("ur_phoenix", "Дева-феникс", "UR", "heroine", 3.0, "/gacha/ur_phoenix.png"))

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
