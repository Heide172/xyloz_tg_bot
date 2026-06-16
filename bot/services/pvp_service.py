"""Гача-v2 PvP (docs/gacha_v2.md).

- `arena_fight_sync` — мгновенный бой против бот-команды (тестовая арена,
  всегда играбельна без второго игрока; даёт данные по винрейтам).
- `matchmake_join_sync` / `matchmake_cancel_sync` — реальный матчмейк через
  Redis-очередь по чату (матч, как только в очереди есть оппонент).
- `ladder_sync` — топ по ELO.

Команда собирается авто: топ-5 карт по силе. Награды: gems + опыт картам +
движение ELO. Все бои логируются в `pvp_battles` (телеметрия).
"""
import json
import os
import secrets

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.clicker_farm import ClickerFarm
from common.models.gacha_collection import GachaCollection
from common.models.pvp_battle import PvpBattle
from services.battle_service import simulate_battle
from services.gacha_catalog import (
    BY_RARITY,
    CATALOG,
    card_ability,
    card_position,
    card_power,
    card_stats,
)
from services.gacha_service import (
    InvalidArgument,
    PVP_LOSS_EXP,
    PVP_WIN_EXP,
    add_card_exp,
)

logger = get_logger(__name__)
_rng = secrets.SystemRandom()

TEAM_SIZE = 5
ELO_K = int(os.getenv("GACHA_PVP_ELO_K", "24"))
WIN_GEMS = int(os.getenv("GACHA_PVP_WIN_GEMS", "1"))
QUEUE_TTL = int(os.getenv("GACHA_PVP_QUEUE_TTL", "180"))  # сек ожидания в очереди
BOT_ELO = 1000

_redis_client = None
_redis_init = False


def _redis():
    global _redis_client, _redis_init
    if _redis_init:
        return _redis_client
    _redis_init = True
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis

        _redis_client = redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    except Exception as exc:
        logger.warning("pvp redis init failed: %s", str(exc)[:160])
        _redis_client = None
    return _redis_client


def _queue_key(chat_id: int) -> str:
    return f"gacha:mm:{chat_id}"


# ---------------- команды ----------------

def _team_card(char_id: str, stars: int, level: int) -> dict:
    c = CATALOG[char_id]
    return {
        "char_id": char_id,
        "name": c.name,
        "rarity": c.rarity,
        "position": card_position(char_id),
        "ability": card_ability(char_id),
        "stars": stars,
        "level": level,
        "stats": card_stats(char_id, stars, level),
    }


def _collect_team(session, user_id: int, chat_id: int):
    """Топ-TEAM_SIZE собственных карт по силе. Возвращает (team_cards, rows)."""
    rows = (
        session.query(GachaCollection)
        .filter(
            GachaCollection.user_id == user_id,
            GachaCollection.chat_id == chat_id,
        )
        .all()
    )
    rows = [r for r in rows if r.char_id in CATALOG]
    rows.sort(key=lambda r: card_power(r.char_id, r.stars, r.level), reverse=True)
    top = rows[:TEAM_SIZE]
    team = [_team_card(r.char_id, r.stars, r.level) for r in top]
    return team, top


def auto_team_sync(user_id: int, chat_id: int) -> dict:
    session = SessionLocal()
    try:
        team, _ = _collect_team(session, user_id, chat_id)
        power = sum(card_power(c["char_id"], c["stars"], c["level"]) for c in team)
        return {"team": team, "power": power, "size": len(team)}
    finally:
        session.close()


def _bot_team(power_hint: int) -> list:
    """Бот-команда близкой силы: подбираем редкости/уровни под power_hint."""
    if power_hint <= 0:
        picks = [("r_cherry", 1, 1), ("r_lemon", 1, 1), ("r_bell", 1, 1),
                 ("r_star", 1, 1), ("r_diamond", 1, 1)]
        return [_team_card(*p) for p in picks]
    target = power_hint / TEAM_SIZE
    team = []
    pool = BY_RARITY["UR"] + BY_RARITY["SSR"] + BY_RARITY["SR"] + BY_RARITY["R"]
    for i in range(TEAM_SIZE):
        # подобрать (char, stars, level) с силой ~target
        best, best_d = None, None
        for _ in range(24):
            cid = _rng.choice(pool)
            stars = _rng.randint(1, 5)
            level = _rng.randint(1, 40)
            d = abs(card_power(cid, stars, level) - target)
            if best_d is None or d < best_d:
                best, best_d = (cid, stars, level), d
        team.append(_team_card(*best))
    return team


def _elo_update(r_a: int, r_b: int, a_won: bool) -> int:
    exp_a = 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))
    score = 1.0 if a_won else 0.0
    return int(round(r_a + ELO_K * (score - exp_a)))


def _grant_rewards(session, farm: ClickerFarm, rows, won: bool) -> dict:
    """Награды одной стороне: gems (победа) + опыт картам."""
    exp = PVP_WIN_EXP if won else PVP_LOSS_EXP
    for r in rows:
        add_card_exp(r, exp)
    gems = WIN_GEMS if won else 0
    if gems:
        farm.gems = (farm.gems or 0) + gems
    return {"gems": gems, "exp_each": exp}


def _snapshot(team: list) -> list:
    return [{"char_id": c["char_id"], "name": c["name"], "rarity": c["rarity"],
             "stars": c["stars"], "level": c["level"], "position": c["position"]}
            for c in team]


def arena_fight_sync(user_id: int, chat_id: int) -> dict:
    """Бой против бот-команды близкой силы. Всегда играбелен (тестовая арена)."""
    session = SessionLocal()
    try:
        from services.clicker_service import _get_or_create_farm

        farm = _get_or_create_farm(session, user_id, chat_id)
        team, rows = _collect_team(session, user_id, chat_id)
        if not team:
            raise InvalidArgument("Нет карт для боя — соберите хотя бы одну в крутке")
        power = sum(card_power(c["char_id"], c["stars"], c["level"]) for c in team)
        bot = _bot_team(power)
        seed = _rng.randrange(1 << 30)
        res = simulate_battle(team, bot, seed)
        won = res["winner"] == "a"
        rewards = _grant_rewards(session, farm, rows, won)
        old_elo = farm.pvp_elo
        farm.pvp_elo = _elo_update(farm.pvp_elo, BOT_ELO, won)
        if won:
            farm.pvp_wins += 1
        else:
            farm.pvp_losses += 1
        battle = PvpBattle(
            chat_id=chat_id, kind="arena", a_user_id=user_id, b_user_id=None,
            winner=res["winner"], winner_user_id=(user_id if won else None),
            rounds=res["rounds"], stake=0,
            team_a=_snapshot(team), team_b=_snapshot(bot), log=res["log"],
        )
        session.add(battle)
        session.commit()
        return {
            "result": "win" if won else "loss",
            "winner": res["winner"], "rounds": res["rounds"], "log": res["log"],
            "team": _snapshot(team), "enemy": _snapshot(bot),
            "rewards": rewards, "elo": farm.pvp_elo, "elo_delta": farm.pvp_elo - old_elo,
            "gems": farm.gems,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_pvp(session, a_user, b_user, chat_id, team_a, rows_a, team_b, rows_b):
    """Провести реальный бой двух игроков, начислить награды/ELO обоим."""
    from services.clicker_service import _get_or_create_farm

    farm_a = _get_or_create_farm(session, a_user, chat_id)
    farm_b = _get_or_create_farm(session, b_user, chat_id)
    seed = _rng.randrange(1 << 30)
    res = simulate_battle(team_a, team_b, seed)
    a_won = res["winner"] == "a"
    _grant_rewards(session, farm_a, rows_a, a_won)
    _grant_rewards(session, farm_b, rows_b, not a_won)
    ea, eb = farm_a.pvp_elo, farm_b.pvp_elo
    farm_a.pvp_elo = _elo_update(ea, eb, a_won)
    farm_b.pvp_elo = _elo_update(eb, ea, not a_won)
    if a_won:
        farm_a.pvp_wins += 1
        farm_b.pvp_losses += 1
        winner_user = a_user
    else:
        farm_b.pvp_wins += 1
        farm_a.pvp_losses += 1
        winner_user = b_user
    session.add(PvpBattle(
        chat_id=chat_id, kind="matchmake", a_user_id=a_user, b_user_id=b_user,
        winner=res["winner"], winner_user_id=winner_user, rounds=res["rounds"],
        stake=0, team_a=_snapshot(team_a), team_b=_snapshot(team_b), log=res["log"],
    ))
    return res, winner_user


def matchmake_join_sync(user_id: int, chat_id: int) -> dict:
    """Встать в очередь матчмейка. Если кто-то уже ждёт — мгновенный бой."""
    session = SessionLocal()
    try:
        team, rows = _collect_team(session, user_id, chat_id)
        if not team:
            raise InvalidArgument("Нет карт для боя — соберите хотя бы одну в крутке")
        cli = _redis()
        if cli is None:
            session.close()
            raise InvalidArgument("Матчмейк недоступен (нет Redis) — используй арену")
        key = _queue_key(chat_id)
        # вытащить ожидающего оппонента (не себя)
        opponent = None
        skipped = []
        try:
            while True:
                raw = cli.lpop(key)
                if raw is None:
                    break
                entry = json.loads(raw)
                if entry.get("user_id") == user_id:
                    continue  # свой старый билет — выбрасываем
                opponent = entry
                break
        except Exception as exc:
            logger.warning("pvp queue pop failed: %s", str(exc)[:160])
        for s in skipped:
            try:
                cli.rpush(key, s)
            except Exception:
                pass

        if opponent is None:
            # встать в очередь (TTL чистит протухшие билеты)
            try:
                cli.rpush(key, json.dumps({"user_id": user_id}))
                cli.expire(key, QUEUE_TTL)
            except Exception as exc:
                logger.warning("pvp queue push failed: %s", str(exc)[:160])
            return {"matched": False, "queued": True, "team": _snapshot(team)}

        opp_id = opponent["user_id"]
        opp_team, opp_rows = _collect_team(session, opp_id, chat_id)
        if not opp_team:
            # у оппонента уже нет карт — встаём в очередь сами
            cli.rpush(key, json.dumps({"user_id": user_id}))
            cli.expire(key, QUEUE_TTL)
            return {"matched": False, "queued": True, "team": _snapshot(team)}
        res, winner_user = _resolve_pvp(
            session, user_id, opp_id, chat_id, team, rows, opp_team, opp_rows
        )
        session.commit()
        a_won = winner_user == user_id
        return {
            "matched": True,
            "result": "win" if a_won else "loss",
            "opponent_id": opp_id,
            "winner": res["winner"], "rounds": res["rounds"], "log": res["log"],
            "team": _snapshot(team), "enemy": _snapshot(opp_team),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass


def matchmake_cancel_sync(user_id: int, chat_id: int) -> dict:
    cli = _redis()
    if cli is None:
        return {"cancelled": False}
    key = _queue_key(chat_id)
    removed = 0
    try:
        items = cli.lrange(key, 0, -1) or []
        cli.delete(key)
        for raw in items:
            entry = json.loads(raw)
            if entry.get("user_id") == user_id:
                removed += 1
                continue
            cli.rpush(key, raw)
        if cli.llen(key):
            cli.expire(key, QUEUE_TTL)
    except Exception as exc:
        logger.warning("pvp queue cancel failed: %s", str(exc)[:160])
    return {"cancelled": removed > 0}


def ladder_sync(chat_id: int, limit: int = 20) -> dict:
    session = SessionLocal()
    try:
        from common.models.user import User

        rows = (
            session.query(ClickerFarm)
            .filter(ClickerFarm.chat_id == chat_id)
            .order_by(ClickerFarm.pvp_elo.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        out = []
        for r in rows:
            u = session.query(User).filter(User.id == r.user_id).first()
            name = None
            if u is not None:
                name = getattr(u, "username", None) or getattr(u, "first_name", None)
            out.append({
                "user_id": r.user_id,
                "name": name or f"id{r.user_id}",
                "elo": r.pvp_elo,
                "wins": r.pvp_wins,
                "losses": r.pvp_losses,
            })
        return {"ladder": out}
    finally:
        session.close()
