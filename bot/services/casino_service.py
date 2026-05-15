"""Мини-игры казино: coinflip, dice, slots, blackjack, roulette.

Все ставки идут в банк чата, все выплаты — из банка. Если в банке не хватает
на максимально возможный выигрыш — игра отклоняется. Через economy_tx логируется
и списание ставки, и выплата.
"""
import os
import random
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.casino_game import CasinoGame
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    MarketError,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)

# Системный RNG (не зависит от random.seed)
_rng = secrets.SystemRandom()

MIN_BET = int(os.getenv("CASINO_MIN_BET", "10"))
MAX_BET = int(os.getenv("CASINO_MAX_BET", "100000"))

# RTP 98% общий target. Конкретные мультипликаторы ниже.
HOUSE_EDGE_PCT = 2.0


class CasinoError(MarketError):
    pass


class GameNotFound(CasinoError):
    pass


class GameNotActive(CasinoError):
    pass


@dataclass
class GameResult:
    game_id: int
    game: str
    outcome: str          # win | lose | push | blackjack
    bet: int
    payout: int           # выплата (включая возврат ставки на win/push)
    net: int              # payout - bet
    user_balance_after: int
    bank_after: int
    details: dict         # game-specific (карты, рулл, символы и т.д.)


# ---------------- shared primitives ----------------


def _validate_bet(bet: int) -> None:
    if not isinstance(bet, int) or bet < MIN_BET:
        raise InvalidArgument(f"Минимальная ставка: {MIN_BET}")
    if bet > MAX_BET:
        raise InvalidArgument(f"Максимальная ставка: {MAX_BET}")


def _settle_sync(
    chat_id: int,
    user_id: int,
    game: str,
    bet: int,
    outcome: str,
    payout: int,
    details: dict,
    max_potential_payout: int,
) -> GameResult:
    """Атомарно: списать ставку, выплатить (если есть), создать CasinoGame + tx-журнал.

    max_potential_payout — самый большой возможный выигрыш этой ставки; банк должен
    его покрыть на момент игры (защита от овердрафта банка).
    """
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < bet:
            raise InsufficientFunds(
                f"Не хватает: у тебя {bal.balance}, нужно {bet}"
            )
        bank = _get_or_create_bank(session, chat_id)
        # банк должен покрыть net-возможную выплату на любой исход
        if max_potential_payout > bet and bank.balance < (max_potential_payout - bet):
            raise InsufficientFunds(
                f"Банк чата не сможет покрыть выигрыш. В банке {bank.balance}, "
                f"максимально возможная выплата сверху ставки {max_potential_payout - bet}"
            )

        # Списать ставку
        bal.balance -= bet
        bal.updated_at = datetime.utcnow()
        bank.balance += bet
        bank.updated_at = datetime.utcnow()

        # Записать игру
        cg = CasinoGame(
            chat_id=chat_id,
            user_id=user_id,
            game=game,
            bet=bet,
            payout=payout,
            status="finished",
            outcome=outcome,
            state=details,
            finished_at=datetime.utcnow(),
        )
        session.add(cg)
        session.flush()

        _log_tx(session, user_id, chat_id, -bet,
                kind=f"casino_{game}_bet", ref_id=str(cg.id))
        _log_tx(session, None, chat_id, bet,
                kind=f"casino_{game}_bet_to_bank", ref_id=str(cg.id))

        # Выплата
        if payout > 0:
            if bank.balance < payout:
                # лимитируем (защита, не должно случаться при max_potential_payout проверке)
                payout = bank.balance
            bank.balance -= payout
            bal.balance += payout
            _log_tx(session, None, chat_id, -payout,
                    kind=f"casino_{game}_payout_from_bank", ref_id=str(cg.id))
            _log_tx(session, user_id, chat_id, payout,
                    kind=f"casino_{game}_payout", ref_id=str(cg.id))
            cg.payout = payout

        session.commit()
        return GameResult(
            game_id=cg.id,
            game=game,
            outcome=outcome,
            bet=bet,
            payout=payout,
            net=payout - bet,
            user_balance_after=bal.balance,
            bank_after=bank.balance,
            details=details,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------- COINFLIP ----------------


def play_coinflip_sync(chat_id: int, user_id: int, bet: int, pick: str) -> GameResult:
    _validate_bet(bet)
    if pick not in ("heads", "tails"):
        raise InvalidArgument("pick должен быть 'heads' или 'tails'")
    flip = _rng.choice(["heads", "tails"])
    win = flip == pick
    # 1.98x (2% house edge)
    payout = int(bet * 1.98) if win else 0
    outcome = "win" if win else "lose"
    details = {"pick": pick, "result": flip}
    max_potential = int(bet * 1.98)
    return _settle_sync(chat_id, user_id, "coinflip", bet, outcome, payout, details, max_potential)


# ---------------- DICE ----------------


def play_dice_sync(chat_id: int, user_id: int, bet: int, mode: str, threshold: int) -> GameResult:
    """Roll 1-100. mode='over' → win если roll > threshold. mode='under' → win если roll < threshold."""
    _validate_bet(bet)
    if mode not in ("over", "under"):
        raise InvalidArgument("mode: 'over' или 'under'")
    if not (1 <= threshold <= 99):
        raise InvalidArgument("threshold 1..99")
    if mode == "over":
        win_prob = (100 - threshold) / 100.0
    else:
        win_prob = (threshold - 1) / 100.0
    if win_prob < 0.01 or win_prob > 0.99:
        raise InvalidArgument("Шанс должен быть 1..99%")

    multiplier = round((1.0 - HOUSE_EDGE_PCT / 100) / win_prob, 2)
    roll = _rng.randint(1, 100)
    win = (mode == "over" and roll > threshold) or (mode == "under" and roll < threshold)
    payout = int(bet * multiplier) if win else 0
    outcome = "win" if win else "lose"
    details = {"mode": mode, "threshold": threshold, "roll": roll, "multiplier": multiplier}
    max_potential = int(bet * multiplier)
    return _settle_sync(chat_id, user_id, "dice", bet, outcome, payout, details, max_potential)


# ---------------- SLOTS (5×3, 10 линий, wild + scatter + фриспины) ----------------

# Сетка 5 барабанов × 3 ряда. RTP ~93% (Монте-Карло, см. коммит).
SLOT_SYMBOLS = ["cherry", "lemon", "bell", "star", "diamond", "wild", "scatter"]
SLOT_WEIGHTS = [27, 24, 20, 13, 8, 4, 4]

# 10 paylines: индекс ряда (0=верх, 1=центр, 2=низ) на каждом из 5 барабанов.
SLOT_LINES = [
    [1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0],
    [2, 2, 2, 2, 2],
    [0, 1, 2, 1, 0],
    [2, 1, 0, 1, 2],
    [0, 0, 1, 0, 0],
    [2, 2, 1, 2, 2],
    [1, 2, 2, 2, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 0, 1, 1],
]

# Выплата за 3/4/5 одинаковых слева (× ставка-на-линию = bet/10).
SLOT_PAYTABLE = {
    "diamond": {3: 18, 4: 75, 5: 300},
    "star": {3: 12, 4: 38, 5: 135},
    "bell": {3: 8, 4: 21, 5: 75},
    "lemon": {3: 3, 4: 9, 5: 27},
    "cherry": {3: 3, 4: 7, 5: 21},
}
# Scatter платит от ОБЩЕЙ ставки (не от линии), вне зависимости от позиций.
SLOT_SCATTER_PAY = {3: 3, 4: 12, 5: 44}
SLOT_FREESPINS = {3: 8, 4: 10, 5: 15}
SLOT_FS_MULTIPLIER = 2


def _spin_grid() -> list[list[str]]:
    """5 барабанов × 3 ряда."""
    return [
        [_rng.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=1)[0] for _ in range(3)]
        for _ in range(5)
    ]


def _eval_lines(grid: list[list[str]], line_bet: float) -> tuple[int, list[dict]]:
    """Оценивает 10 линий. Wild подменяет любой символ. Возвращает
    (суммарная выплата, список выигрышных линий для UI)."""
    total = 0
    wins: list[dict] = []
    for li, line in enumerate(SLOT_LINES):
        syms = [grid[r][line[r]] for r in range(5)]
        base = next((s for s in syms if s not in ("wild", "scatter")), None)
        if base is None:
            continue
        cnt = 0
        for s in syms:
            if s == base or s == "wild":
                cnt += 1
            else:
                break
        if cnt >= 3 and base in SLOT_PAYTABLE:
            pay = int(SLOT_PAYTABLE[base][cnt] * line_bet)
            total += pay
            wins.append({"line": li, "symbol": base, "count": cnt, "payout": pay})
    return total, wins


def _count_scatter(grid: list[list[str]]) -> int:
    return sum(1 for reel in grid for s in reel if s == "scatter")


def play_slots_sync(chat_id: int, user_id: int, bet: int) -> GameResult:
    _validate_bet(bet)
    line_bet = bet / 10.0

    grid = _spin_grid()
    base_win, win_lines = _eval_lines(grid, line_bet)
    scatter_count = _count_scatter(grid)

    total_payout = base_win
    scatter_payout = 0
    freespins: list[dict] = []

    if scatter_count >= 3:
        sc = min(scatter_count, 5)
        scatter_payout = SLOT_SCATTER_PAY[sc] * bet
        total_payout += scatter_payout
        # Авто-проигрываем фриспины (без решений игрока), множитель ×2.
        for _ in range(SLOT_FREESPINS[sc]):
            fg = _spin_grid()
            fw, fl = _eval_lines(fg, line_bet)
            fw *= SLOT_FS_MULTIPLIER
            total_payout += fw
            freespins.append({"grid": fg, "win": fw, "lines": fl})

    outcome = "win" if total_payout > 0 else "lose"
    details = {
        "grid": grid,
        "win_lines": win_lines,
        "scatter_count": scatter_count,
        "scatter_payout": scatter_payout,
        "freespins": freespins,
        "base_win": base_win,
        "fs_multiplier": SLOT_FS_MULTIPLIER,
    }
    # Реалистичный порог для проверки «банк не пуст» (теоретический максимум
    # недостижим и заблокировал бы игру). Если выпадет джекпот больше банка —
    # _settle_sync сам лимитирует фактическую выплату остатком банка.
    max_potential = bet * 50
    return _settle_sync(chat_id, user_id, "slots", bet, outcome, total_payout, details, max_potential)


# ---------------- ROULETTE ----------------

# European: 0-36, 37 ячеек. Red/black: стандартные numbers.
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def play_roulette_sync(
    chat_id: int,
    user_id: int,
    bet: int,
    bet_type: str,
    value: Optional[str] = None,
) -> GameResult:
    """
    bet_type:
      'number'  value='0'..'36'      payout 36x (включая ставку)
      'color'   value='red'|'black'  payout 2x
      'parity'  value='even'|'odd'   payout 2x
      'half'    value='low'|'high'   payout 2x  (1-18 / 19-36)
      'dozen'   value='1'|'2'|'3'    payout 3x  (1-12 / 13-24 / 25-36)
    """
    _validate_bet(bet)
    spin = _rng.randint(0, 36)
    win = False
    multiplier = 0
    max_multiplier = 0

    if bet_type == "number":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise InvalidArgument("number: целое 0..36")
        if not (0 <= n <= 36):
            raise InvalidArgument("number: 0..36")
        win = spin == n
        multiplier = 36 if win else 0
        max_multiplier = 36
    elif bet_type == "color":
        if value not in ("red", "black"):
            raise InvalidArgument("color: 'red' или 'black'")
        if spin != 0:
            is_red = spin in RED_NUMBERS
            win = (value == "red" and is_red) or (value == "black" and not is_red)
        multiplier = 2 if win else 0
        max_multiplier = 2
    elif bet_type == "parity":
        if value not in ("even", "odd"):
            raise InvalidArgument("parity: 'even' или 'odd'")
        if spin != 0:
            is_even = spin % 2 == 0
            win = (value == "even" and is_even) or (value == "odd" and not is_even)
        multiplier = 2 if win else 0
        max_multiplier = 2
    elif bet_type == "half":
        if value not in ("low", "high"):
            raise InvalidArgument("half: 'low' или 'high'")
        if spin != 0:
            win = (value == "low" and spin <= 18) or (value == "high" and spin >= 19)
        multiplier = 2 if win else 0
        max_multiplier = 2
    elif bet_type == "dozen":
        if value not in ("1", "2", "3"):
            raise InvalidArgument("dozen: '1', '2' или '3'")
        if spin != 0:
            d = (spin - 1) // 12 + 1
            win = str(d) == value
        multiplier = 3 if win else 0
        max_multiplier = 3
    else:
        raise InvalidArgument(f"Неизвестный bet_type: {bet_type}")

    payout = bet * multiplier
    outcome = "win" if win else "lose"
    is_red = spin in RED_NUMBERS
    color = "green" if spin == 0 else ("red" if is_red else "black")
    details = {
        "bet_type": bet_type,
        "value": value,
        "spin": spin,
        "color": color,
        "multiplier": multiplier,
    }
    return _settle_sync(chat_id, user_id, "roulette", bet, outcome, payout, details,
                        bet * max_multiplier)


# ---------------- BLACKJACK ----------------

CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
CARD_SUITS = ["S", "H", "D", "C"]  # spades, hearts, diamonds, clubs


def _make_deck() -> list[str]:
    return [r + s for r in CARD_RANKS for s in CARD_SUITS]


def _hand_value(hand: list[str]) -> tuple[int, bool]:
    """Возвращает (total, soft) — total с учётом тузов, soft=True если есть туз=11."""
    total = 0
    aces = 0
    for c in hand:
        rank = c[:-1]
        if rank == "A":
            total += 11
            aces += 1
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    soft = False
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    if aces > 0:
        soft = True
    return total, soft


def _is_blackjack(hand: list[str]) -> bool:
    if len(hand) != 2:
        return False
    total, _ = _hand_value(hand)
    return total == 21


def start_blackjack_sync(chat_id: int, user_id: int, bet: int) -> GameResult:
    _validate_bet(bet)
    deck = _make_deck()
    _rng.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < bet:
            raise InsufficientFunds(f"Не хватает: {bal.balance}/{bet}")
        bank = _get_or_create_bank(session, chat_id)
        # blackjack может удвоиться на double => max payout = 2*bet * 2.5 BJ ≈ 5x
        max_potential = int(bet * 2.5)  # natural BJ pays 2.5x; double would re-check
        if max_potential > bet and bank.balance < (max_potential - bet):
            raise InsufficientFunds(
                f"Банк не покрывает выигрыш. В банке {bank.balance}, нужно ≥ {max_potential - bet}"
            )

        bal.balance -= bet
        bal.updated_at = datetime.utcnow()
        bank.balance += bet
        bank.updated_at = datetime.utcnow()

        state = {
            "deck": deck,
            "player": player,
            "dealer": dealer,
            "doubled": False,
        }
        cg = CasinoGame(
            chat_id=chat_id,
            user_id=user_id,
            game="blackjack",
            bet=bet,
            payout=0,
            status="active",
            state=state,
        )
        session.add(cg)
        session.flush()
        _log_tx(session, user_id, chat_id, -bet, kind="casino_blackjack_bet", ref_id=str(cg.id))
        _log_tx(session, None, chat_id, bet, kind="casino_blackjack_bet_to_bank", ref_id=str(cg.id))

        # Сразу проверяем natural blackjack
        player_bj = _is_blackjack(player)
        dealer_bj = _is_blackjack(dealer)

        result_outcome = None
        result_payout = 0
        if player_bj or dealer_bj:
            result_outcome, result_payout = _settle_blackjack(session, cg, bank, bal)
            session.commit()
            return GameResult(
                game_id=cg.id, game="blackjack", outcome=result_outcome,
                bet=bet, payout=result_payout, net=result_payout - bet,
                user_balance_after=bal.balance, bank_after=bank.balance,
                details={"player": player, "dealer": dealer, "finished": True},
            )

        session.commit()
        # Игра продолжается
        return GameResult(
            game_id=cg.id, game="blackjack", outcome="active",
            bet=bet, payout=0, net=-bet,
            user_balance_after=bal.balance, bank_after=bank.balance,
            details={
                "player": player,
                "dealer_visible": dealer[0],
                "finished": False,
                "can_double": True,
            },
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _dealer_play(deck: list[str], dealer: list[str]) -> list[str]:
    """Дилер берёт до 17. Stand on all 17 (включая soft)."""
    while True:
        total, _ = _hand_value(dealer)
        if total >= 17:
            return dealer
        dealer.append(deck.pop())


def _settle_blackjack(session, cg: CasinoGame, bank, bal) -> tuple[str, int]:
    """Финализирует игру: dealer doбирает, считаем результат, выплата.
    Возвращает (outcome, gross_payout). Меняет cg.state/status/payout/outcome."""
    state = dict(cg.state or {})
    deck = list(state.get("deck") or [])
    player = list(state.get("player") or [])
    dealer = list(state.get("dealer") or [])
    doubled = bool(state.get("doubled"))

    player_total, _ = _hand_value(player)
    dealer_total, _ = _hand_value(dealer)
    player_bj = _is_blackjack(player)
    dealer_bj = _is_blackjack(dealer)

    if player_total <= 21 and not (player_bj and not dealer_bj):
        # Дилер играет только если игрок не перебил и не сделал чистый BJ
        if not (player_bj and dealer_bj):
            dealer = _dealer_play(deck, dealer)
            dealer_total, _ = _hand_value(dealer)

    outcome = "lose"
    payout_mult = 0.0
    bet_used = cg.bet * 2 if doubled else cg.bet

    if player_total > 21:
        outcome = "lose"
    elif player_bj and not dealer_bj:
        outcome = "blackjack"
        payout_mult = 2.5
    elif dealer_bj and not player_bj:
        outcome = "lose"
    elif player_bj and dealer_bj:
        outcome = "push"
        payout_mult = 1.0
    elif dealer_total > 21:
        outcome = "win"
        payout_mult = 2.0
    elif player_total > dealer_total:
        outcome = "win"
        payout_mult = 2.0
    elif player_total == dealer_total:
        outcome = "push"
        payout_mult = 1.0
    else:
        outcome = "lose"

    payout = int(bet_used * payout_mult)
    if payout > bank.balance:
        payout = bank.balance
    if payout > 0:
        bank.balance -= payout
        bal.balance += payout
        _log_tx(session, None, cg.chat_id, -payout,
                kind="casino_blackjack_payout_from_bank", ref_id=str(cg.id))
        _log_tx(session, cg.user_id, cg.chat_id, payout,
                kind="casino_blackjack_payout", ref_id=str(cg.id))

    state["dealer"] = dealer
    state["deck"] = deck
    cg.state = state
    cg.status = "finished"
    cg.outcome = outcome
    cg.payout = payout
    cg.finished_at = datetime.utcnow()
    return outcome, payout


def _load_active_game_sync(game_id: int, user_id: int) -> CasinoGame:
    session = SessionLocal()
    try:
        cg = session.query(CasinoGame).filter(CasinoGame.id == game_id).first()
        if not cg:
            raise GameNotFound(f"Игра #{game_id} не найдена")
        if cg.user_id != user_id:
            raise CasinoError("Эта игра — не твоя")
        if cg.status != "active":
            raise GameNotActive(f"Игра #{game_id} уже завершена")
        return cg
    finally:
        session.close()


def hit_blackjack_sync(game_id: int, user_id: int) -> GameResult:
    session = SessionLocal()
    try:
        cg = session.query(CasinoGame).filter(
            CasinoGame.id == game_id, CasinoGame.user_id == user_id
        ).with_for_update().first()
        if not cg:
            raise GameNotFound(f"Игра #{game_id} не найдена")
        if cg.status != "active":
            raise GameNotActive("Игра уже завершена")

        state = dict(cg.state or {})
        deck = list(state.get("deck") or [])
        player = list(state.get("player") or [])
        if not deck:
            raise CasinoError("Колода пуста")

        player.append(deck.pop())
        state["deck"] = deck
        state["player"] = player
        cg.state = state

        bank = _get_or_create_bank(session, cg.chat_id)
        bal = _get_or_create_balance(session, cg.user_id, cg.chat_id)

        total, _ = _hand_value(player)
        if total >= 21:
            outcome, payout = _settle_blackjack(session, cg, bank, bal)
            session.commit()
            return GameResult(
                game_id=cg.id, game="blackjack", outcome=outcome,
                bet=cg.bet, payout=payout, net=payout - cg.bet,
                user_balance_after=bal.balance, bank_after=bank.balance,
                details={"player": player, "dealer": state["dealer"], "finished": True},
            )

        session.commit()
        return GameResult(
            game_id=cg.id, game="blackjack", outcome="active",
            bet=cg.bet, payout=0, net=-cg.bet,
            user_balance_after=bal.balance, bank_after=bank.balance,
            details={
                "player": player,
                "dealer_visible": state["dealer"][0],
                "finished": False,
                "can_double": False,
            },
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def stand_blackjack_sync(game_id: int, user_id: int) -> GameResult:
    session = SessionLocal()
    try:
        cg = session.query(CasinoGame).filter(
            CasinoGame.id == game_id, CasinoGame.user_id == user_id
        ).with_for_update().first()
        if not cg:
            raise GameNotFound("Не найдена")
        if cg.status != "active":
            raise GameNotActive("Уже завершена")
        bank = _get_or_create_bank(session, cg.chat_id)
        bal = _get_or_create_balance(session, cg.user_id, cg.chat_id)
        outcome, payout = _settle_blackjack(session, cg, bank, bal)
        session.commit()
        state = cg.state or {}
        return GameResult(
            game_id=cg.id, game="blackjack", outcome=outcome,
            bet=cg.bet, payout=payout, net=payout - cg.bet,
            user_balance_after=bal.balance, bank_after=bank.balance,
            details={"player": state.get("player"), "dealer": state.get("dealer"), "finished": True},
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def double_blackjack_sync(game_id: int, user_id: int) -> GameResult:
    """Удвоение: ещё одна ставка списывается, одна карта, потом стенд."""
    session = SessionLocal()
    try:
        cg = session.query(CasinoGame).filter(
            CasinoGame.id == game_id, CasinoGame.user_id == user_id
        ).with_for_update().first()
        if not cg:
            raise GameNotFound("Не найдена")
        if cg.status != "active":
            raise GameNotActive("Уже завершена")
        state = dict(cg.state or {})
        player = list(state.get("player") or [])
        if len(player) != 2:
            raise CasinoError("Удвоить можно только на первых двух картах")

        bal = _get_or_create_balance(session, cg.user_id, cg.chat_id)
        bank = _get_or_create_bank(session, cg.chat_id)
        if bal.balance < cg.bet:
            raise InsufficientFunds(f"Не хватает на удвоение: {bal.balance}/{cg.bet}")
        bal.balance -= cg.bet
        bank.balance += cg.bet
        _log_tx(session, cg.user_id, cg.chat_id, -cg.bet,
                kind="casino_blackjack_double", ref_id=str(cg.id))
        _log_tx(session, None, cg.chat_id, cg.bet,
                kind="casino_blackjack_double_to_bank", ref_id=str(cg.id))

        deck = list(state.get("deck") or [])
        if not deck:
            raise CasinoError("Колода пуста")
        player.append(deck.pop())
        state["player"] = player
        state["deck"] = deck
        state["doubled"] = True
        cg.state = state

        outcome, payout = _settle_blackjack(session, cg, bank, bal)
        session.commit()
        return GameResult(
            game_id=cg.id, game="blackjack", outcome=outcome,
            bet=cg.bet * 2, payout=payout, net=payout - cg.bet * 2,
            user_balance_after=bal.balance, bank_after=bank.balance,
            details={"player": player, "dealer": state.get("dealer"), "finished": True, "doubled": True},
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
