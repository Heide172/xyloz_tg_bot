"""Агрегированная статистика чата для лидерборда."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from api.auth import TgWebAppAuth, ensure_db_user, require_auth, require_chat_membership
from common.db.db import SessionLocal

router = APIRouter()


class PlayerStat(BaseModel):
    tg_id: int
    username: str | None
    fullname: str | None
    balance: int
    casino_net: int          # выигрыш - ставки по всем казино-играм
    casino_staked: int
    casino_won: int
    farm_earned: int         # сконвертировано с фермы (clicker_mint)
    games_played: int


class BiggestWin(BaseModel):
    username: str | None
    fullname: str | None
    game: str
    bet: int
    payout: int
    created_at: str


class StatsResponse(BaseModel):
    players: list[PlayerStat]
    biggest_wins: list[BiggestWin]


@router.get("", response_model=StatsResponse)
async def stats(auth: TgWebAppAuth = Depends(require_auth)) -> StatsResponse:
    chat_id = await require_chat_membership(auth)
    ensure_db_user(auth)
    s = SessionLocal()
    try:
        # Сводка по игрокам: баланс + казино + ферма
        rows = s.execute(
            text("""
            WITH cas AS (
              SELECT user_id,
                SUM(CASE WHEN kind LIKE 'casino_%_bet' THEN -amount ELSE 0 END) staked,
                SUM(CASE WHEN kind LIKE 'casino_%_payout' THEN amount ELSE 0 END) won,
                COUNT(*) FILTER (WHERE kind LIKE 'casino_%_bet') games
              FROM economy_tx
              WHERE chat_id = :c AND user_id IS NOT NULL
                AND kind LIKE 'casino_%'
                AND kind NOT LIKE '%_to_bank' AND kind NOT LIKE '%_from_bank'
              GROUP BY user_id
            ),
            farm AS (
              SELECT user_id, SUM(amount) earned
              FROM economy_tx
              WHERE chat_id = :c AND user_id IS NOT NULL AND kind = 'clicker_mint'
              GROUP BY user_id
            )
            SELECT u.tg_id, u.username, u.fullname,
                   COALESCE(ub.balance,0),
                   COALESCE(cas.staked,0), COALESCE(cas.won,0),
                   COALESCE(cas.games,0), COALESCE(farm.earned,0)
            FROM user_balance ub
            JOIN users u ON u.id = ub.user_id
            LEFT JOIN cas  ON cas.user_id  = ub.user_id
            LEFT JOIN farm ON farm.user_id = ub.user_id
            WHERE ub.chat_id = :c
            ORDER BY ub.balance DESC
            """),
            {"c": chat_id},
        ).fetchall()

        players = [
            PlayerStat(
                tg_id=int(r[0]),
                username=r[1],
                fullname=r[2],
                balance=int(r[3]),
                casino_staked=int(r[4]),
                casino_won=int(r[5]),
                casino_net=int(r[5]) - int(r[4]),
                games_played=int(r[6]),
                farm_earned=int(r[7]),
            )
            for r in rows
        ]

        bw = s.execute(
            text("""
            SELECT u.username, u.fullname, cg.game, cg.bet, cg.payout, cg.created_at
            FROM casino_games cg
            JOIN users u ON u.id = cg.user_id
            WHERE cg.chat_id = :c AND cg.payout > cg.bet
            ORDER BY (cg.payout - cg.bet) DESC
            LIMIT 10
            """),
            {"c": chat_id},
        ).fetchall()
        biggest = [
            BiggestWin(
                username=r[0],
                fullname=r[1],
                game=r[2],
                bet=int(r[3]),
                payout=int(r[4]),
                created_at=r[5].isoformat(),
            )
            for r in bw
        ]
        return StatsResponse(players=players, biggest_wins=biggest)
    finally:
        s.close()
