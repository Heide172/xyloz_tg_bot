"""Admin API: операции, которые раньше были в /admin_adjust, /market_*, и т.д."""
import asyncio
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TgWebAppAuth, is_admin, require_auth, require_chat_membership
from common.db.db import SessionLocal
from common.models.chat_bank import ChatBank
from common.models.economy_tx import EconomyTx
from common.models.user_balance import UserBalance
from services.economy_service import (
    InsufficientFunds,
    credit,
    debit,
    resolve_user_by_username,
)
from services.markets_service import (
    InvalidArgument,
    MarketError,
    MarketNotFound,
    cancel_market,
    resolve_market,
)
from services.feedback_service import (
    close as fb_close,
    default_reward as fb_default_reward,
    get_one as fb_get_one,
    list_open as fb_list_open,
)

router = APIRouter()


def _ensure_admin(auth: TgWebAppAuth) -> None:
    if not is_admin(auth.user.id):
        raise HTTPException(status_code=403, detail="Только для админов бота.")


# ---------------- balance / bank adjust ----------------


class BalanceAdjustReq(BaseModel):
    target: str = Field(min_length=1, description="@username или tg_id")
    amount: int = Field(description="±N — может быть отрицательным")
    note: Optional[str] = None


class BalanceAdjustResp(BaseModel):
    user_id: int
    username: Optional[str] = None
    new_balance: int


def _resolve_target_user(target: str):
    target = target.strip()
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", target)
    if m:
        u = resolve_user_by_username(m.group(1))
        if u is None:
            raise HTTPException(status_code=404, detail=f"Юзер {target} не найден")
        return u
    try:
        tg_id = int(target)
    except ValueError:
        raise HTTPException(status_code=400, detail="Укажи @username или tg_id")
    from common.models.user import User

    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == tg_id).first()
        if u is None:
            raise HTTPException(status_code=404, detail=f"tg_id {tg_id} не найден")
        return u
    finally:
        session.close()


def _do_balance_adjust(chat_id: int, target_user_id: int, amount: int, note: Optional[str]) -> int:
    if amount == 0:
        raise InvalidArgument("Сумма не должна быть нулевой")
    if amount > 0:
        return credit(target_user_id, chat_id, amount, kind="admin_adjust", note=note)
    return debit(target_user_id, chat_id, -amount, kind="admin_adjust", note=note)


@router.post("/balance_adjust", response_model=BalanceAdjustResp)
async def balance_adjust(req: BalanceAdjustReq, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    target = _resolve_target_user(req.target)
    try:
        new_balance = await asyncio.to_thread(
            _do_balance_adjust, chat_id, target.id, req.amount, req.note
        )
    except InsufficientFunds as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BalanceAdjustResp(user_id=target.id, username=target.username, new_balance=new_balance)


class BankAdjustReq(BaseModel):
    amount: int
    note: Optional[str] = None


class BankAdjustResp(BaseModel):
    new_balance: int


def _do_bank_adjust(chat_id: int, amount: int, note: Optional[str]) -> int:
    session = SessionLocal()
    try:
        bank = session.query(ChatBank).filter(ChatBank.chat_id == chat_id).with_for_update().first()
        if bank is None:
            bank = ChatBank(chat_id=chat_id, balance=0)
            session.add(bank)
            session.flush()
        new_balance = bank.balance + amount
        if new_balance < 0:
            raise InvalidArgument(f"Банк не уйдёт в минус: текущий {bank.balance}, минимум {-bank.balance}")
        bank.balance = new_balance
        bank.updated_at = datetime.utcnow()
        session.add(EconomyTx(
            user_id=None,
            chat_id=chat_id,
            amount=amount,
            kind="admin_bank_adjust",
            note=note,
        ))
        session.commit()
        return new_balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/bank_adjust", response_model=BankAdjustResp)
async def bank_adjust(req: BankAdjustReq, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    if req.amount == 0:
        raise HTTPException(status_code=400, detail="Сумма не должна быть нулевой")
    try:
        nb = await asyncio.to_thread(_do_bank_adjust, chat_id, req.amount, req.note)
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BankAdjustResp(new_balance=nb)


# ---------------- markets resolve / cancel ----------------
# (создание и импорт рынков — публичные, см. api/routes/markets.py)


class MarketResolveReq(BaseModel):
    winning_option_position: int = Field(ge=1)


@router.post("/markets/{market_id}/resolve")
async def markets_resolve(
    market_id: int, req: MarketResolveReq, auth: TgWebAppAuth = Depends(require_auth)
):
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    # Проверка что рынок этого чата делается внутри resolve_market.
    try:
        result = await asyncio.to_thread(
            resolve_market, market_id=market_id, winning_option_position=req.winning_option_position
        )
    except MarketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidArgument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/markets/{market_id}/cancel")
async def markets_cancel(market_id: int, auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    await require_chat_membership(auth)
    try:
        result = await asyncio.to_thread(cancel_market, market_id)
    except MarketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# ---------------- feedback moderation + награды ----------------
# Фидбэк глобальный (не привязан к текущему чату): членство в чате
# не требуем. Награда начисляется в чат, откуда фидбэк прислан
# (chat_id хранится в строке feedback) — логика в feedback_service.


@router.get("/analytics")
async def usage_analytics(
    hours: int = 24, auth: TgWebAppAuth = Depends(require_auth)
):
    _ensure_admin(auth)
    from services.analytics_service import summary

    return await asyncio.to_thread(summary, max(1, min(hours, 720)), 30)


@router.get("/metrics")
async def perf_metrics(
    reset: int = 0, auth: TgWebAppAuth = Depends(require_auth)
):
    _ensure_admin(auth)
    from common.metrics import reset as m_reset
    from common.metrics import snapshot

    if reset:
        await asyncio.to_thread(m_reset)
    return await asyncio.to_thread(snapshot, 30)


@router.get("/feedback")
async def feedback_list(auth: TgWebAppAuth = Depends(require_auth)):
    _ensure_admin(auth)
    rows = await asyncio.to_thread(fb_list_open, 50)
    return {
        "items": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "text": r["text"],
                "chat_id": r["chat_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "default_reward": fb_default_reward(r["kind"]),
            }
            for r in rows
        ]
    }


class FeedbackCloseReq(BaseModel):
    amount: Optional[int] = Field(
        default=None, description="None = дефолт по типу; 0 = без награды"
    )


def _notify_author(res: dict) -> None:
    atg = res.get("author_tg_id")
    if not atg or not res.get("credited"):
        return
    from services.social_service import send_chat_message

    kind_ru = "баг" if res["kind"] == "bug" else "идею"
    note = (
        f"Спасибо за {kind_ru}! Заявка #{res['id']} закрыта, "
        f"тебе начислено +{res['reward']}г."
    )
    try:
        send_chat_message(atg, note)
    except Exception:
        pass


# ---------------- twin (двойник дня) ----------------


@router.get("/twin")
async def twin_status(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Статус двойника + последние 20 ответов из twin_log."""
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    from services.twin_service import get_state

    def _logs():
        from common.models.twin_log import TwinLog as _TL

        s = SessionLocal()
        try:
            rows = (
                s.query(_TL)
                .filter(_TL.chat_id == chat_id)
                .order_by(_TL.id.desc())
                .limit(20)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "text": r.response_text,
                    "status": r.status,
                    "cost": r.cost,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            s.close()

    state = await asyncio.to_thread(get_state, chat_id)
    logs = await asyncio.to_thread(_logs)
    return {"state": state, "logs": logs}


class TwinToggleReq(BaseModel):
    enabled: bool


@router.post("/twin/toggle")
async def twin_toggle(
    req: TwinToggleReq, auth: TgWebAppAuth = Depends(require_auth)
) -> dict:
    """Вкл/выкл двойника для этого чата."""
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)

    def _do():
        from common.models.chat_twin_state import ChatTwinState

        s = SessionLocal()
        try:
            st = (
                s.query(ChatTwinState)
                .filter(ChatTwinState.chat_id == chat_id)
                .with_for_update()
                .first()
            )
            if not st:
                st = ChatTwinState(chat_id=chat_id, enabled=req.enabled)
                s.add(st)
            else:
                st.enabled = req.enabled
                st.updated_at = datetime.utcnow()
            s.commit()
            return st.enabled
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    enabled = await asyncio.to_thread(_do)
    return {"enabled": enabled}


@router.post("/twin/rotate_now")
async def twin_rotate_now(auth: TgWebAppAuth = Depends(require_auth)) -> dict:
    """Принудительно перезапустить ротацию двойника прямо сейчас (для дебага)."""
    _ensure_admin(auth)
    chat_id = await require_chat_membership(auth)
    from services.twin_service import pick_target_for_day, set_target_for_day

    def _do():
        target = pick_target_for_day(chat_id)
        set_target_for_day(chat_id, target)
        return target

    target = await asyncio.to_thread(_do)
    return {"target": target}


@router.post("/feedback/{fid}/close")
async def feedback_close(
    fid: int,
    req: FeedbackCloseReq,
    auth: TgWebAppAuth = Depends(require_auth),
):
    _ensure_admin(auth)
    existing = await asyncio.to_thread(fb_get_one, fid)
    if not existing:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    res = await asyncio.to_thread(fb_close, fid, req.amount)
    if not res.get("ok"):
        err = res.get("error")
        if err == "already_done":
            raise HTTPException(
                status_code=409,
                detail=f"Уже закрыта (награда была {res.get('reward', 0)}г)",
            )
        if err == "not_found":
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        raise HTTPException(status_code=500, detail="Не удалось закрыть")

    await asyncio.to_thread(_notify_author, res)
    return {
        "ok": True,
        "id": res["id"],
        "kind": res["kind"],
        "reward": res["reward"],
        "credited": res["credited"],
        "chat_id": res.get("chat_id"),
        "author_name": res.get("author_name"),
    }
