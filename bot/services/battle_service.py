"""Гача-v2 auto-battler 5v5 (docs/gacha_v2.md).

`simulate_battle(team_a, team_b, seed)` — чистая детерминированная функция:
одинаковый seed + составы → одинаковый исход и лог. Лог переигрывается
анимацией в UI.

team_* — список карт-словарей (см. pvp_service.team_card):
  {char_id, name, rarity, position('front'|'back'), ability, stars, level,
   stats: {hp, atk, def, spd}}
"""
import random

from services.gacha_catalog import ABILITIES, EVERY_N_ACTIONS

DMG_K = 0.5          # коэффициент защиты в формуле урона
ROUND_CAP = 30       # таймаут боя (раундов)


def _mk(side, idx, card):
    s = card["stats"]
    return {
        "side": side,
        "idx": idx,
        "char_id": card["char_id"],
        "name": card.get("name", card["char_id"]),
        "ability": card.get("ability"),
        "position": card.get("position", "back"),
        "atk": int(s["atk"]),
        "def": int(s["def"]),
        "spd": int(s["spd"]),
        "maxhp": int(s["hp"]),
        "hp": int(s["hp"]),
        "actions": 0,
    }


def _alive(team):
    return [c for c in team if c["hp"] > 0]


def _pick_target(enemies, rng):
    """Цель: живой фронт первым, иначе живой бэк."""
    alive = _alive(enemies)
    if not alive:
        return None
    front = [c for c in alive if c["position"] == "front"]
    pool = front if front else alive
    return rng.choice(pool)


def _raw_dmg(atk, dfn):
    return max(1, int(round(atk - dfn * DMG_K)))


def _team_hp_frac(team):
    mh = sum(c["maxhp"] for c in team) or 1
    return sum(max(0, c["hp"]) for c in team) / mh


def simulate_battle(team_a: list, team_b: list, seed: int = 0) -> dict:
    rng = random.Random(seed)
    A = [_mk("a", i, c) for i, c in enumerate(team_a)]
    B = [_mk("b", i, c) for i, c in enumerate(team_b)]
    by_side = {"a": A, "b": B}
    log = []
    rounds = 0

    def enemies_of(side):
        return B if side == "a" else A

    def allies_of(side):
        return A if side == "a" else B

    while _alive(A) and _alive(B) and rounds < ROUND_CAP:
        rounds += 1
        # порядок хода: по SPD убыв., тай — случайно (детерминирован seed'ом)
        order = sorted(
            _alive(A) + _alive(B),
            key=lambda c: (c["spd"], rng.random()),
            reverse=True,
        )
        for actor in order:
            if actor["hp"] <= 0:
                continue
            enemies = enemies_of(actor["side"])
            allies = allies_of(actor["side"])
            if not _alive(enemies):
                break
            actor["actions"] += 1
            abil = actor["ability"]
            use_ability = bool(abil) and actor["actions"] % EVERY_N_ACTIONS == 0
            cfg = ABILITIES.get(abil) if use_ability else None
            ev = {"round": rounds, "side": actor["side"], "actor": actor["char_id"],
                  "actor_name": actor["name"], "ability": abil if use_ability else None}

            if cfg and cfg["type"] == "heal":
                tgt = min(_alive(allies), key=lambda c: c["hp"] / c["maxhp"])
                heal = int(round(tgt["maxhp"] * cfg["frac"]))
                tgt["hp"] = min(tgt["maxhp"], tgt["hp"] + heal)
                ev.update({"action": "heal", "target": tgt["char_id"], "heal": heal})
            elif cfg and cfg["type"] == "self_heal":
                heal = int(round(actor["maxhp"] * cfg["frac"]))
                actor["hp"] = min(actor["maxhp"], actor["hp"] + heal)
                ev.update({"action": "guard", "target": actor["char_id"], "heal": heal})
            elif cfg and cfg["type"] == "aoe":
                hits = []
                for tgt in _alive(enemies):
                    dmg = _raw_dmg(actor["atk"] * cfg["mult"], tgt["def"])
                    tgt["hp"] -= dmg
                    hits.append({"target": tgt["char_id"], "dmg": dmg})
                ev.update({"action": "aoe", "hits": hits})
            else:
                tgt = _pick_target(enemies, rng)
                if tgt is None:
                    break
                mult = cfg["mult"] if cfg else 1.0
                dmg = _raw_dmg(actor["atk"] * mult, tgt["def"])
                tgt["hp"] -= dmg
                ev.update({"action": "attack", "target": tgt["char_id"], "dmg": dmg})
            log.append(ev)
            if not _alive(enemies):
                break

    a_alive, b_alive = bool(_alive(A)), bool(_alive(B))
    if a_alive and not b_alive:
        winner = "a"
    elif b_alive and not a_alive:
        winner = "b"
    else:
        # таймаут — по доле суммарного HP
        fa, fb = _team_hp_frac(A), _team_hp_frac(B)
        winner = "a" if fa > fb else "b" if fb > fa else "draw"

    return {"winner": winner, "rounds": rounds, "log": log}
